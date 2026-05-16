import os
import traceback
import time
from ..repositories.documents_repository import documents_repo
from ..repositories.users_repository import users_repo
from ..rag.rag_service import rag_service
from ..utils.ocr_utils import ocr_extract, preprocess_for_ocr, ocr_structure_extract, smart_menu_ocr_extract
from ..utils.pdf_utils import extract_text_from_pdf, get_pdf_pages_as_images
from ..utils.word_utils import extract_text_from_word
from ..utils.logger import Log
from ..services.log_service import log_service
from ..utils.cloudinary_utils import cloudinary_service
from ..repositories.users_repository import users_repo
from ..utils.smart_config import get_smart_config
from ..utils.smart_spatial_extractor import SmartSpatialExtractor
from ..utils.ocr_utils import filter_useless_lines
from ..utils.text_cleaner import clean_text_lines
from ..utils.background_tasks import run_background_upload_and_log
from ..utils.post_cleaner import PostCleaner
from ..api.processors.ai_processor import process_with_openai
from ..api.processors.traditional_processor import process_traditional
from ..utils.redis_client import publish_event, redis_conn
from ..utils.file_utils import calculate_files_hash
from ..config import DocStatus
import threading
import json

def silent_cleanup_files(file_paths):
    """Cleanup files in a background thread to avoid blocking the main task completion log."""
    def cleanup():
        if not file_paths:
            return
        # Ensure it's a list
        paths = [file_paths] if isinstance(file_paths, str) else file_paths
        for path in paths:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                    Log.debug(f"[Cleanup] 🗑️ Removed: {path}")
                except Exception as e:
                    Log.debug(f"[Cleanup] ❌ Failed to delete {path}: {e}")
    
    thread = threading.Thread(target=cleanup, daemon=True)
    thread.start()

def process_document_task(doc_id, workspace_id, file_path, original_filename, user_id):
    """
    Background task for RAG indexing
    """
    try:
        start_time = time.time()
        Log.info(f"[Worker] Starting processing document: {original_filename}")
        documents_repo.update_status(doc_id, DocStatus.PROCESSING)
        publish_event(user_id, "document_status", {"document_id": doc_id, "status": DocStatus.PROCESSING})
        
        ext = original_filename.lower().split('.')[-1]
        structured_data = [] # List of {"text": str, "page_num": int}
        
        if ext == 'md':
            with open(file_path, 'r', encoding='utf-8') as f: 
                text = f.read()
                structured_data = [{"text": text, "page_num": 1}]
        elif ext in ['docx', 'doc']:
            text = extract_text_from_word(file_path)
            structured_data = [{"text": text, "page_num": 1}]
        elif ext == 'pdf':
            pages = extract_text_from_pdf(file_path) # Now returns list[dict]
            has_text = any(p['text'].strip() for p in pages)
            
            if not has_text:
                Log.info(f"[Worker] PDF '{original_filename}' has no text, switching to OCR")
                image_paths = get_pdf_pages_as_images(file_path)
                for idx, img_p in enumerate(image_paths):
                    res, _ = ocr_extract(img_p)
                    if res:
                        res = clean_text_lines(res)
                        page_text = "\n".join([line['text'] if isinstance(line, dict) else str(line) for line in res])
                        structured_data.append({"text": page_text, "page_num": idx + 1})
                    if os.path.exists(img_p): os.remove(img_p)
            else:
                structured_data = pages
        elif ext in ['jpg', 'jpeg', 'png', 'bmp']:
            ocr_result, _ = ocr_extract(file_path)
            if ocr_result:
                ocr_result = clean_text_lines(ocr_result)
                text = "\n".join([line['text'] if isinstance(line, dict) else str(line) for line in ocr_result])
                structured_data = [{"text": text, "page_num": 1}]
        
        if structured_data:
            total_chunks = rag_service.index_text(structured_data, workspace_id, original_filename)
            documents_repo.update_status(doc_id, DocStatus.READY, total_chunks=total_chunks)
            publish_event(user_id, "document_status", {"document_id": doc_id, "status": DocStatus.READY})
        else:
            raise Exception("No text could be extracted")
    except Exception as e:
        Log.error(f"[Worker] Failed: {e}")
        documents_repo.update_status(doc_id, DocStatus.FAILED, error_message=str(e))
        publish_event(user_id, "document_status", {"document_id": doc_id, "status": DocStatus.FAILED, "error": str(e)})
    finally:
        if 'file_path' in locals(): silent_cleanup_files(file_path)

def process_detection_task(doc_id, user_id, doc_type, file_paths, provider, raw_text=None, detect_handwriting=False):
    """
    Background task to process document detection.
    Ưu tiên tuyệt đối raw_text nếu có để đảm bảo tốc độ.
    """
    try:
        Log.info(f"[Worker-Detect] Starting detection: {doc_type} (Provider: {provider})")
        documents_repo.update_status(doc_id, DocStatus.PROCESSING)
        publish_event(user_id, "detection_status", {"document_id": doc_id, "status": DocStatus.PROCESSING, "type": doc_type})
        
        request_start = time.time()
        
        # 0. QR Code Fast Path for CCCD
        if not raw_text and doc_type == 'idCard' and file_paths:
            try:
                from pyzbar.pyzbar import decode
                import cv2
                for p in file_paths:
                    if str(p).lower().endswith(('.jpg', '.jpeg', '.png', '.bmp')):
                        img = cv2.imread(p)
                        if img is not None:
                            # Chiến thuật 1: Quét ảnh gốc
                            decoded = decode(img)
                            
                            # Chiến thuật 2: Nếu thất bại, thử phóng to ảnh (Upscale) - Hiệu quả với QR nhỏ/mờ
                            if not decoded:
                                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                                upscale = cv2.resize(gray, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
                                decoded = decode(upscale)
                                
                                # Chiến thuật 3: Thử cân bằng xám/độ tương phản (Thresholding)
                                if not decoded:
                                    _, thresh = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
                                    decoded = decode(thresh)

                            if decoded:
                                qr_text = decoded[0].data.decode('utf-8')
                                if '|' in qr_text:
                                    Log.info(f"\n{'='*70}\n[Worker-Detect] 🚀 [THÀNH CÔNG] ĐÃ ĐỌC ĐƯỢC MÃ QR CCCD:\n{qr_text}\n{'='*70}\n")
                                    raw_text = qr_text
                                    break
                
                if not raw_text:
                    Log.info("[Worker-Detect] ⚠️ Không tìm thấy mã QR hợp lệ trong ảnh. Chuyển sang bước OCR...")
            except ImportError:
                Log.warning("[Worker-Detect] Thư viện pyzbar chưa được cài đặt. Bỏ qua quét QR.")
            except Exception as e:
                Log.warning(f"[Worker-Detect] Lỗi khi quét QR: {e}")

        # 1. Manual KIE Fast Path (Specific for CCCD/DriverLicense if raw_text format matches)
        manual_data = None
        if raw_text:
            if doc_type == 'idCard' and '|' in raw_text:
                Log.info("[Worker-Detect] ⚡ Manual KIE Fast-Path activated for CCCD")
                manual_data = PostCleaner.extract_cccd_manual(raw_text)
                Log.info(f"\n{'*'*70}\n[Worker-Detect] 🎯 [KẾT QUẢ TỪ QR] DỮ LIỆU ĐƯỢC BÓC TÁCH:\n{json.dumps(manual_data, indent=4, ensure_ascii=False)}\n{'*'*70}\n")
            elif doc_type == 'driverLicense':
                Log.info("[Worker-Detect] ⚡ Manual KIE Fast-Path activated for DriverLicense")
                manual_data = PostCleaner.extract_driver_manual(raw_text)

        if manual_data:
            total_time = time.time() - request_start
            
            # Quota increment for manual extraction
            if user_id:
                users_repo.increment_extraction_stats(user_id, doc_type)
                Log.info(f"[Worker-Detect] 📊 Quota incremented for Manual KIE (User: {user_id})")
            
            # Trigger Background Upload and Logging for consistency
            from ..utils.background_tasks import run_background_upload_and_log
            metadata = {
                "total_time": f"{total_time:.2f}s",
                "provider": "manual_kie"
            }
            run_background_upload_and_log(user_id, doc_type, file_paths, manual_data, metadata=metadata, document_id=doc_id)
            
            documents_repo.update_status(doc_id, DocStatus.READY, result=manual_data, debug={"total_time": f"{total_time:.2f}s", "provider": "manual_kie"})
            publish_event(user_id, "detection_status", {"document_id": doc_id, "status": DocStatus.READY, "type": doc_type, "result": manual_data, "debug": {"provider": "manual_kie"}})
            return

        # 2. Source Stage (Sequential XOR: raw_text OR OCR)

        raw_front, raw_back = [], []
        ocr_front_time, ocr_back_time = 0.0, 0.0
        
        # UU TIEN 1: raw_text (Speed)
        if raw_text:
            Log.info(f"[Worker-Detect] 📝 Using raw_text source (Skipping OCR for speed)")
            for line in raw_text.split('\n'):
                if line.strip(): 
                    raw_front.append({"text": line.strip(), "box": [[0,0],[0,0],[0,0],[0,0]], "score": 1.0})
        
        # UU TIEN 2: file_paths (OCR)
        elif len(file_paths) > 0:
            Log.info(f"[Worker-Detect] 🔍 No raw_text provided. Starting OCR stage...")
            
            # 🖼️ Expand PDF to Images if needed
            all_images = []
            input_paths = list(file_paths) # Safe copy
            
            def check_is_pdf(path_file):
                if path_file.lower().endswith('.pdf'): return True
                try:
                    with open(path_file, 'rb') as f:
                        return f.read(4) == b'%PDF'
                except:
                    return False

            native_pdf_text = []

            for p in input_paths:
                if check_is_pdf(p):
                    # Step 1: Try PyMuPDF native text extraction first
                    pages = extract_text_from_pdf(p)
                    has_text = any(page.get('text', '').strip() for page in pages)
                    
                    if has_text:
                        Log.info(f"[Worker-Detect] 📄 PDF '{p}' has native text, extracting directly...")
                        for page in pages:
                            if page.get('text'):
                                native_pdf_text.append(page['text'])
                    else:
                        Log.info(f"[Worker-Detect] 📄 Expanding PDF to images: {p}")
                        pdf_imgs = get_pdf_pages_as_images(p)
                        all_images.extend(pdf_imgs)
                        # Add new temp images to file_paths so they get cleaned up in finally block
                        file_paths.extend(pdf_imgs)
                else:
                    all_images.append(p)

            # If we successfully extracted native PDF text and there are no other pure images
            if native_pdf_text and not all_images:
                Log.info(f"[Worker-Detect] 📝 Using native PDF text source (Skipping OCR)")
                raw_text_combined = "\n".join(native_pdf_text)
                for line in raw_text_combined.split('\n'):
                    if line.strip(): 
                        raw_front.append({"text": line.strip(), "box": [[0,0],[0,0],[0,0],[0,0]], "score": 1.0})
                ocr_front_time, ocr_back_time = 0.0, 0.0
                # Bypassing OCR flag
                all_images = []
            elif not all_images and not native_pdf_text:
                raise Exception("No valid images found for OCR (PDF might be empty or invalid)")

            # OCR for all collected images
            if all_images:
                ocr_results = []
                ocr_times = []
                # CHẾ ĐỘ MỚI: Dùng Structure V3 cho Invoice và Menu
                
                for img_p in all_images:
                    t = time.time()
                    # Sử dụng OCR V5 truyền thống (Mobile) cho tất cả các loại tài liệu theo yêu cầu
                    res, _ = ocr_extract(img_p, img=preprocess_for_ocr(img_p), detect_handwriting=detect_handwriting)
                    ocr_results.append(res)
                    ocr_times.append(time.time() - t)
                
                raw_front = ocr_results[0]
                raw_back = []
                if len(ocr_results) > 1:
                    # Combine all subsequent pages into raw_back
                    for res in ocr_results[1:]:
                        raw_back.extend(res)
                
                ocr_front_time = ocr_times[0]
                ocr_back_time = sum(ocr_times[1:]) if len(ocr_times) > 1 else 0.0
        else:
            raise Exception("No input source (text or image) provided")

        # [CLEANING DISABLED] Toàn bộ dữ liệu thô từ OCR được chuyển thẳng cho AI xử lý theo yêu cầu.

        timer_info = {"start": request_start, "ocr_front": ocr_front_time, "ocr_back": ocr_back_time}
        
        # 4. Processing Phase
        result_response = None
        
        # Luôn ưu tiên dùng AI Processor cho idCard như yêu cầu
        if provider != 'traditional' or doc_type == 'idCard':
            try:
                Log.info(f"[Worker-Detect] Dùng AI Processor cho {doc_type}")
                result_response = process_with_openai(raw_front, raw_back, timer_info, doc_type, user_id, file_paths, document_id=doc_id)
            except Exception as e:
                Log.error(f"[Worker-Detect] OpenAI failed: {e}")

        # Chỉ dùng Traditional cho các loại giấy tờ khác nếu được yêu cầu hoặc AI lỗi
        if result_response is None:
            Log.info(f"[Worker-Detect] Fallback sang Traditional Processor cho {doc_type}")
            result_response = process_traditional(raw_front, raw_back, timer_info, doc_type, user_id, file_paths, document_id=doc_id)

        # 5. Completion
        if result_response:
            debug_info = result_response.get("debug")
            if not isinstance(debug_info, dict):
                debug_info = {}
            if detect_handwriting:
                debug_info["model"] = "vietocr-handwritten-finetune"
            documents_repo.update_status(doc_id, DocStatus.READY, result=result_response.get("data"), debug=debug_info)
            publish_event(user_id, "detection_status", {"document_id": doc_id, "status": DocStatus.READY, "type": doc_type, "result": result_response.get("data"), "debug": debug_info})
            pass # No caching needed
        else:
            raise Exception("Processing failed to return result")
            
    except Exception as e:
        Log.error(f"[Worker-Detect] Failed: {e}")
        documents_repo.update_status(doc_id, DocStatus.FAILED, error_message=str(e))
        publish_event(user_id, "detection_status", {"document_id": doc_id, "status": DocStatus.FAILED, "type": doc_type, "error": str(e)})
        
        # Push error log to database and upload to Cloudinary for debugging
        try:
            from ..utils.background_tasks import run_background_upload_and_log
            if 'file_paths' in locals() and file_paths:
                metadata = {"status": "failed", "error": str(e)}
                # Copy file_paths to prevent thread conflicts, though both may attempt cleanup
                run_background_upload_and_log(user_id, doc_type, list(file_paths), {"error": str(e)}, metadata=metadata, document_id=doc_id)
                # Clear local file_paths so finally block doesn't delete them before upload finishes
                file_paths = []
        except Exception as log_e:
            Log.error(f"[Worker-Detect] Failed to trigger error background log: {log_e}")
    finally:
        if 'file_paths' in locals() and file_paths: silent_cleanup_files(file_paths)

def process_structure_detection_task(doc_id, user_id, doc_type, file_paths, provider, raw_text=None, detect_handwriting=False):
    """
    Hàm bổ sung: Xử lý trích xuất sử dụng PP-Structure V3.
    Dành riêng cho các loại tài liệu có cấu trúc phức tạp (Hóa đơn, Menu).
    """
    Log.info(f"[Worker-Structure] 🏗️ Starting structure detection task: {doc_type}")
    # Gọi process_detection_task để tái sử dụng toàn bộ logic quản lý Document, Event và AI Processing.
    # Bên trong process_detection_task đã có logic switch sang ocr_structure_extract nếu doc_type là invoice/menu.
    return process_detection_task(doc_id, user_id, doc_type, file_paths, provider, raw_text=raw_text, detect_handwriting=detect_handwriting)

