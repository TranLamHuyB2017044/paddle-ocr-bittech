import os
import traceback
import time
from src.modules.ocr.repositories.documents_repository import documents_repo
from src.modules.auth.repositories.users_repository import users_repo
from src.modules.ocr.utils.ocr_utils import ocr_extract, preprocess_for_ocr, ocr_structure_extract, smart_menu_ocr_extract
from ..utils.pdf_utils import extract_text_from_pdf, get_pdf_pages_as_images, extract_page_text_with_tables
from ..utils.word_utils import extract_text_from_word
from ..utils.logger import Log
from ..utils.background_tasks import run_background_upload_and_log
from src.modules.ocr.utils.post_cleaner import PostCleaner
from src.modules.ocr.processors.ai_processor import process_with_openai
from src.modules.ocr.processors.traditional_processor import process_traditional
from src.modules.rag.rag_service import rag_service
from ..utils.redis_client import publish_event, redis_conn
from src.core.config import DocStatus
import threading
import json

def extract_text_with_vision_llm(image_path: str) -> str:
    from src.shared.extractors.gemini_extractor import gemini_extractor
    import PIL.Image
    
    if not gemini_extractor.is_configured or not gemini_extractor.client:
        raise Exception("Gemini is not configured")
        
    img = PIL.Image.open(image_path)
    prompt = "Trích xuất chính xác và đầy đủ toàn bộ văn bản có trong hình ảnh này. Giữ nguyên định dạng đoạn văn bản. Trả về văn bản thuần túy, không định dạng markdown."
    
    response = gemini_extractor.client.models.generate_content(
        model=gemini_extractor.model_name,
        contents=[prompt, img]
    )
    text = response.text.strip()
    if not text:
        raise Exception("Empty response from Vision LLM")
    return text

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

def process_document_task(doc_id, workspace_id, file_path, original_filename, user_id, vision_extract=False):
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
            import fitz
            try:
                doc = fitz.open(file_path)
                for idx in range(len(doc)):
                    page = doc[idx]
                    page_text = page.get_text().strip()
                    has_images = len(page.get_images()) > 0
                    
                    # Cần OCR nếu trang trống hoặc text quá ngắn (< 200 ký tự) và có chứa hình ảnh
                    needs_ocr = not page_text or (len(page_text) < 200 and has_images)
                    
                    if needs_ocr:
                        Log.info(f"[Worker] PDF page {idx+1} needs OCR (text len: {len(page_text)}, images: {has_images})")
                        try:
                            from src.core.config import root_dir
                            abs_temp_dir = os.path.join(root_dir, "uploads/temp")
                            os.makedirs(abs_temp_dir, exist_ok=True)
                            
                            import uuid
                            img_path = os.path.join(abs_temp_dir, f"{uuid.uuid4()}_p{idx}.jpg")
                            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
                            pix.save(img_path)
                            
                            text = None
                            if vision_extract:
                                try:
                                    Log.info(f"[Worker] Using Vision LLM for RAG PDF page {idx+1}")
                                    text = extract_text_with_vision_llm(img_path)
                                    from src.core.config import VISION_LLM_COST
                                    users_repo.increment_extraction_stats(user_id, "document", cost=VISION_LLM_COST)
                                except Exception as e:
                                    Log.warning(f"[Worker] Vision LLM RAG failed for page {idx+1}: {e}. Fallback to traditional OCR.")
                            
                            if not text:
                                res, _ = ocr_extract(img_path)
                                if res:
                                    text = "\n".join([line['text'] if isinstance(line, dict) else str(line) for line in res])
                            
                            if text:
                                structured_data.append({"text": text, "page_num": idx + 1})
                            else:
                                structured_data.append({"text": page_text, "page_num": idx + 1})
                                
                            if os.path.exists(img_path):
                                os.remove(img_path)
                        except Exception as e:
                            Log.error(f"[Worker] Failed to OCR page {idx+1}: {e}")
                            structured_data.append({"text": page_text, "page_num": idx + 1})
                    else:
                        Log.info(f"[Worker] PDF page {idx+1} has native text (len: {len(page_text)})")
                        page_text_extracted = extract_page_text_with_tables(page)
                        structured_data.append({"text": page_text_extracted, "page_num": idx + 1})
                doc.close()
            except Exception as e:
                Log.error(f"[Worker] Failed to process PDF page-by-page: {e}")
                # Fallback to extract_text_from_pdf
                pages = extract_text_from_pdf(file_path)
                structured_data = pages
        elif ext in ['jpg', 'jpeg', 'png', 'bmp']:
            text = None
            if vision_extract:
                try:
                    Log.info(f"[Worker] Using Vision LLM for RAG image: {original_filename}")
                    text = extract_text_with_vision_llm(file_path)
                    # Trừ quota cho Vision LLM
                    from src.core.config import VISION_LLM_COST
                    users_repo.increment_extraction_stats(user_id, "document", cost=VISION_LLM_COST)
                except Exception as e:
                    Log.warning(f"[Worker] Vision LLM RAG failed for image: {e}. Fallback to traditional OCR.")
            
            if not text:
                ocr_result, _ = ocr_extract(file_path)
                if ocr_result:
                    text = "\n".join([line['text'] if isinstance(line, dict) else str(line) for line in ocr_result])
            
            if text:
                structured_data = [{"text": text, "page_num": 1}]
        
        if structured_data:
            # Lưu toàn bộ nội dung văn bản thô vào MongoDB để hỗ trợ reindex sau này
            # mà không cần file gốc
            combined_raw_text = "\n\n".join(
                str(item.get("text", "")) for item in structured_data if isinstance(item.get("text"), str) and str(item.get("text", "")).strip()
            )
            total_chunks = rag_service.index_text(structured_data, workspace_id, original_filename)
            documents_repo.update_status(
                doc_id, DocStatus.READY,
                total_chunks=total_chunks,
                raw_text=combined_raw_text
            )
            publish_event(user_id, "document_status", {"document_id": doc_id, "status": DocStatus.READY})
        else:
            raise Exception("No text could be extracted")

    except Exception as e:
        Log.error(f"[Worker] Failed: {e}")
        documents_repo.update_status(doc_id, DocStatus.FAILED, error_message=str(e))
        publish_event(user_id, "document_status", {"document_id": doc_id, "status": DocStatus.FAILED, "error": str(e)})
    finally:
        if 'file_path' in locals(): silent_cleanup_files(file_path)

def process_detection_task(doc_id, user_id, doc_type, file_paths, provider, raw_text=None, detect_handwriting=False, vision_extract=False):
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
                                qr_text = decoded[0].data.decode('utf-8', errors='replace')
                                qr_text = PostCleaner.repair_encoding(qr_text)
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

        # 1.4. Optimize Cost: Check if PDF or Word doc has native text. If yes, disable Vision LLM to save costs.
        if (detect_handwriting or vision_extract) and not raw_text and file_paths:
            def check_is_pdf_fast(path_file):
                if str(path_file).lower().endswith('.pdf'): return True
                try:
                    with open(path_file, 'rb') as f: return f.read(4) == b'%PDF'
                except: return False
                
            def check_is_word_fast(path_file):
                return str(path_file).lower().endswith(('.docx', '.doc'))

            has_native_text = False
            for p in file_paths:
                if check_is_pdf_fast(p):
                    try:
                        pages = extract_text_from_pdf(p)
                        if any(page.get('text', '').strip() for page in pages):
                            has_native_text = True
                            break
                    except:
                        pass
                elif check_is_word_fast(p):
                    try:
                        text = extract_text_from_word(p)
                        if text and text.strip():
                            has_native_text = True
                            break
                    except:
                        pass
                        
            if has_native_text:
                Log.info(f"[Worker-Detect] 💰 PDF/Word document has native selectable text. Disabling Vision LLM to optimize costs.")
                detect_handwriting = False
                vision_extract = False

        # 1.5. Vision LLM Fast Path for Handwriting or Vision Extract Flag
        if (detect_handwriting or vision_extract) and not raw_text and file_paths:
            Log.info(f"[Worker-Detect] 📝 Vision LLM flag is True. Bypassing traditional OCR, using Vision LLM directly...")
            from ..api.processors.ai_processor import process_with_vision_llm
            
            # Tách và chuyển đổi PDF sang ảnh nếu cần thiết trước khi gửi cho Vision LLM
            vision_paths = []
            for p in list(file_paths):
                if p.lower().endswith('.pdf'):
                    Log.info(f"[Worker-Detect] 📄 Expanding PDF to images for Vision LLM: {p}")
                    try:
                        pdf_imgs = get_pdf_pages_as_images(p)
                        if pdf_imgs:
                            vision_paths.extend(pdf_imgs)
                            # Lưu vào file_paths chính để tự động xóa khi kết thúc task
                            file_paths.extend(pdf_imgs)
                    except Exception as pdf_err:
                        Log.error(f"[Worker-Detect] ❌ Failed to convert PDF {p} to images for Vision: {pdf_err}")
                elif p.lower().endswith(('.docx', '.doc')):
                    Log.warning(f"[Worker-Detect] ⚠️ Word document {p} cannot be processed by Vision LLM directly. Skipping image conversion.")
                else:
                    vision_paths.append(p)

            if not vision_paths:
                raise Exception("Không tìm thấy tệp ảnh hoặc PDF hợp lệ để xử lý bằng Vision LLM")
            
            # Khởi tạo timer info đơn giản cho Vision LLM
            timer_info = {"start": request_start, "ocr_front": 0, "ocr_back": 0}
            result_response = process_with_vision_llm(vision_paths, timer_info, doc_type, user_id, document_id=doc_id)
            
            if result_response:
                debug_info = result_response.get("debug", {})
                documents_repo.update_status(doc_id, DocStatus.READY, result=result_response.get("data"), debug=debug_info)
                publish_event(user_id, "detection_status", {"document_id": doc_id, "status": DocStatus.READY, "type": doc_type, "result": result_response.get("data"), "debug": debug_info})
                return
            else:
                raise Exception("Vision LLM Processing failed to return result")

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
            
            # 🖼️ Expand PDF to Images or Extract Native PDF/Word Text if needed
            all_images = []
            input_paths = list(file_paths) # Safe copy
            
            def check_is_pdf(path_file):
                if path_file.lower().endswith('.pdf'): return True
                try:
                    with open(path_file, 'rb') as f:
                        return f.read(4) == b'%PDF'
                except:
                    return False

            def check_is_word(path_file):
                return path_file.lower().endswith(('.docx', '.doc'))

            def check_is_excel(path_file):
                return path_file.lower().endswith('.xlsx')

            native_doc_text = []

            for p in input_paths:
                if check_is_pdf(p):
                    pages = extract_text_from_pdf(p)
                    
                    # Kiểm tra xem PDF có trang nào là trang scan hay không
                    is_scanned = True
                    if pages:
                        import fitz
                        try:
                            doc = fitz.open(p)
                            is_scanned = False
                            for idx in range(len(doc)):
                                page = doc[idx]
                                page_text = page.get_text().strip()
                                has_images = len(page.get_images()) > 0
                                # Nếu trang trống hoặc text quá ngắn và chứa ảnh, coi là trang scan
                                if not page_text or (len(page_text) < 200 and has_images):
                                    is_scanned = True
                                    break
                            doc.close()
                        except Exception as e:
                            Log.warning(f"[Worker-Detect] Error checking PDF scan status: {e}")
                            is_scanned = not any(page.get('text', '').strip() for page in pages)
                    
                    if not is_scanned:
                        Log.info(f"[Worker-Detect] 📄 PDF '{p}' has native text, extracting directly...")
                        for page in pages:
                            if page.get('text'):
                                native_doc_text.append(page['text'])
                    else:
                        Log.info(f"[Worker-Detect] 📄 PDF '{p}' appears to be scanned/image-based, expanding to images for OCR...")
                        pdf_imgs = get_pdf_pages_as_images(p)
                        all_images.extend(pdf_imgs)
                        # Add new temp images to file_paths so they get cleaned up in finally block
                        file_paths.extend(pdf_imgs)
                elif check_is_word(p):
                    Log.info(f"[Worker-Detect] 📄 Word document '{p}' detected, extracting text directly...")
                    try:
                        w_text = extract_text_from_word(p)
                        if w_text and w_text.strip():
                            native_doc_text.append(w_text)
                    except Exception as w_err:
                        Log.error(f"[Worker-Detect] ❌ Failed to extract text from Word document {p}: {w_err}")
                elif check_is_excel(p):
                    Log.info(f"[Worker-Detect] 📄 Excel document '{p}' detected, extracting text directly...")
                    try:
                        import openpyxl
                        wb = openpyxl.load_workbook(p, data_only=True)
                        excel_text_lines = []
                        for sheet_name in wb.sheetnames:
                            ws = wb[sheet_name]
                            excel_text_lines.append(f"--- Sheet: {sheet_name} ---")
                            for row in ws.iter_rows(values_only=True):
                                row_text = "  |  ".join([str(val).strip() for val in row if val is not None])
                                if row_text.strip():
                                    excel_text_lines.append(row_text)
                        
                        e_text = "\n".join(excel_text_lines)
                        if e_text.strip():
                            native_doc_text.append(e_text)
                    except Exception as e_err:
                        Log.error(f"[Worker-Detect] ❌ Failed to extract text from Excel document {p}: {e_err}")
                else:
                    all_images.append(p)

            # If we successfully extracted native PDF/Word/Excel text and there are no other pure images
            if native_doc_text and not all_images:
                Log.info(f"[Worker-Detect] 📝 Using native PDF/Word/Excel text source (Skipping OCR)")
                raw_text_combined = "\n".join(native_doc_text)
                for line in raw_text_combined.split('\n'):
                    if line.strip(): 
                        raw_front.append({"text": line.strip(), "box": [[0,0],[0,0],[0,0],[0,0]], "score": 1.0})
                ocr_front_time, ocr_back_time = 0.0, 0.0
                # Bypassing OCR flag
                all_images = []
            elif not all_images and not native_doc_text:
                raise Exception("No valid documents or images found for OCR/Extraction")

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

def process_structure_detection_task(doc_id, user_id, doc_type, file_paths, provider, raw_text=None, detect_handwriting=False, vision_extract=False):
    """
    Hàm bổ sung: Xử lý trích xuất sử dụng PP-Structure V3.
    Dành riêng cho các loại tài liệu có cấu trúc phức tạp (Hóa đơn, Menu).
    """
    Log.info(f"[Worker-Structure] 🏗️ Starting structure detection task: {doc_type}")
    # Gọi process_detection_task để tái sử dụng toàn bộ logic quản lý Document, Event và AI Processing.
    # Bên trong process_detection_task đã có logic switch sang ocr_structure_extract nếu doc_type là invoice/menu.
    return process_detection_task(doc_id, user_id, doc_type, file_paths, provider, raw_text=raw_text, detect_handwriting=detect_handwriting, vision_extract=vision_extract)


def process_tts_task(tts_id, text, voice_sample_path=None, voice_name=None):
    """
    Background task to process text-to-speech generation on the worker.
    """
    from src.modules.tts.services import tts_service
    from src.shared.utils.redis_client import redis_conn
    from src.core.config import FILES_API_URL, FILES_API_UPLOAD_ENDPOINT, FILES_API_SYSTEM_ID, FILES_API_USER_ID, FILES_API_ALIAS, FILES_API_KEY
    from src.shared.utils.logger import Log
    import json
    import requests
    import os
    import traceback
    
    output_wav_path = None
    try:
        Log.info(f"[Worker-TTS] Bắt đầu tạo TTS cho tác vụ {tts_id}")
        output_wav_path = tts_service.synthesize(
            text=text,
            voice_sample_path=voice_sample_path,
            voice_name=voice_name
        )
        
        # Upload file to external API
        Log.info(f"[Worker-TTS] Đang tải file lên API bên ngoài: {output_wav_path}")
        upload_url = f"{FILES_API_URL}{FILES_API_UPLOAD_ENDPOINT}"
        
        with open(output_wav_path, 'rb') as f:
            files = {
                'files': (os.path.basename(output_wav_path), f, 'audio/wav')
            }
            data = {
                'system_id': FILES_API_SYSTEM_ID,
                'user_id': FILES_API_USER_ID,
                'alias': FILES_API_ALIAS,
                "file_system": False
            }
            headers = {
                'x-api-key': FILES_API_KEY
            }
            
            Log.info(f"[Worker-TTS] Gửi yêu cầu đến: {upload_url}")
            # SECURITY: Không log headers chứa API key ra stdout
            _safe_headers = {k: (v[:4] + "****" if "key" in k.lower() or "token" in k.lower() or "auth" in k.lower() else v) for k, v in headers.items()}
            Log.debug(f"[Worker-TTS] Headers (masked): {_safe_headers}")
            
            response = requests.post(upload_url, files=files, data=data, headers=headers, timeout=30)
            
            Log.info(f"[Worker-TTS] Phản hồi từ API bên ngoài - Status Code: {response.status_code}")
            # Chỉ log summary, không log full response body (tránh lộ dữ liệu nội bộ)
            try:
                _resp_json = response.json()
                _summary = _resp_json.get("data", {}).get("summary", {})
                Log.info(f"[Worker-TTS] Upload summary: {_summary}")
            except Exception:
                Log.info(f"[Worker-TTS] Upload hoàn tất (không parse được JSON)")
            
            response.raise_for_status()
            upload_response = response.json()
            
            # Enrich full path URL using FILES_API_URL + publicPath
            base_url = (FILES_API_URL or "https://files.bittechx.cloud").rstrip('/')
            data_obj = upload_response.get("data") if isinstance(upload_response, dict) else None
            if isinstance(data_obj, dict):
                results = data_obj.get("results", [])
                if isinstance(results, list):
                    for item in results:
                        if isinstance(item, dict):
                            file_info = item.get("file")
                            if isinstance(file_info, dict):
                                public_path = file_info.get("publicPath") or file_info.get("path")
                                if public_path:
                                    full_url = f"{base_url}/{public_path.lstrip('/')}"
                                    file_info["url"] = full_url
                                    item["url"] = full_url
                                    if "url" not in data_obj:
                                        data_obj["url"] = full_url
                                    if "url" not in upload_response:
                                        upload_response["url"] = full_url
        
        # Publish success result with upload response
        result = {
            "status": "success",
            "output_path": output_wav_path,
            "upload_response": upload_response
        }
        redis_conn.publish(f"tts_channel_{tts_id}", json.dumps(result))
        Log.info(f"[Worker-TTS] Completed TTS generation and upload for task {tts_id}")
    except requests.exceptions.RequestException as e:
        Log.error(f"[Worker-TTS] Lỗi kết nối API bên ngoài cho tác vụ {tts_id}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            Log.error(f"[Worker-TTS] Nội dung phản hồi lỗi: {e.response.text}")
        result = {
            "status": "failed",
            "error": str(e)
        }
        redis_conn.publish(f"tts_channel_{tts_id}", json.dumps(result))
    except Exception as e:
        Log.error(f"[Worker-TTS] Failed TTS generation for task {tts_id}: {e}")
        Log.error(f"[Worker-TTS] Stack trace: {traceback.format_exc()}")
        result = {
            "status": "failed",
            "error": str(e)
        }
        redis_conn.publish(f"tts_channel_{tts_id}", json.dumps(result))
    finally:
        # Cleanup temp file
        if output_wav_path and os.path.exists(output_wav_path):
            try:
                os.remove(output_wav_path)
                Log.info(f"[Worker-TTS] Đã xóa file tạm: {output_wav_path}")
            except Exception as e:
                Log.warning(f"[Worker-TTS] Không thể xóa file tạm {output_wav_path}: {e}")

