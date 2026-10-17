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

def process_document_task(doc_id, workspace_id, file_path, original_filename, user_id, vision_extract=False, category: str | None = None):
    """
    Background task for RAG indexing
    """
    try:
        start_time = time.time()
        Log.info(f"[Worker] Starting processing document: {original_filename} (Category: {category})")
        documents_repo.update_status(doc_id, DocStatus.PROCESSING)
        publish_event(user_id, "document_status", {"document_id": doc_id, "status": DocStatus.PROCESSING})
        
        ext = original_filename.lower().split('.')[-1]
        structured_data = [] # List of {"text": str, "page_num": int}
        
        total_ocr_wall_time = 0.0
        
        if ext == 'md':
            with open(file_path, 'r', encoding='utf-8') as f: 
                text = f.read()
                structured_data = [{"text": text, "page_num": 1}]
        elif ext in ['docx', 'doc']:
            text = extract_text_from_word(file_path)
            structured_data = [{"text": text, "page_num": 1}]
        elif ext == 'pdf':
            import fitz
            from concurrent.futures import ThreadPoolExecutor, as_completed
            try:
                doc = fitz.open(file_path)
                total_pages = len(doc)
                Log.info(f"[Worker] 🚀 Bắt đầu xử lý PDF '{original_filename}' với {total_pages} trang (Mode: {'Vision LLM' if vision_extract else 'PaddleOCR'})")
                
                # Mảng lưu kết quả theo đúng thứ tự trang
                page_results = [None] * total_pages
                pages_needing_ocr = [] # danh sách (idx, fallback_text)
                
                # Bước 1: Quét nhanh các trang có sẵn native text (chỉ mất ~0.2s cho toàn bộ PDF)
                for idx in range(total_pages):
                    page = doc[idx]
                    page_text = page.get_text().strip()
                    has_images = len(page.get_images()) > 0
                    needs_ocr = not page_text or (len(page_text) < 200 and has_images)
                    
                    if not needs_ocr:
                        page_text_extracted = extract_page_text_with_tables(page)
                        page_results[idx] = {"text": page_text_extracted, "page_num": idx + 1}
                    else:
                        pages_needing_ocr.append((idx, page_text))
                
                doc.close() # Đóng handle fitz chính sau khi quét
                
                native_count = total_pages - len(pages_needing_ocr)
                Log.info(f"[Worker] 📊 PDF '{original_filename}': {native_count} trang có sẵn text, {len(pages_needing_ocr)} trang cần OCR")
                
                # Bước 2: Xử lý các trang cần OCR
                if pages_needing_ocr:
                    # Cho phép xử lý song song nhiều trang cùng lúc (mặc định 2 trang, tinh chỉnh qua PDF_OCR_WORKERS).
                    # Tự động cân bằng số luồng nhận dạng dòng chữ (OCR_THREADS):
                    # workers_count * OCR_THREADS <= 4 Cores CPU của container.
                    # Nhờ đó 2 trang chạy song song chỉ mất ~7s/trang (thay vì vọt lên 20s do nghẽn 16 luồng như trước),
                    # và tổng thời gian tài liệu nhanh hơn 30% so với chạy tuần tự.
                    if vision_extract:
                        workers_count = int(os.getenv("PDF_VISION_WORKERS", "8"))
                    else:
                        workers_count = int(os.getenv("PDF_OCR_WORKERS", "2"))
                        balanced_threads = max(1, 4 // workers_count)
                        os.environ["OCR_THREADS"] = str(balanced_threads)
                        Log.info(f"[Worker] ⚙️ Cấu hình OCR song song: {workers_count} trang cùng lúc, {balanced_threads} luồng nhận dạng/trang")
                    
                    ocr_start_time = time.time()
                    page_ocr_times = {}

                    def process_single_ocr_page(page_info):
                        p_idx, fallback_text = page_info
                        t_page_start = time.time()
                        try:
                            # Mở handle riêng trong worker thread để thread-safe tuyệt đối
                            sub_doc = fitz.open(file_path)
                            sub_page = sub_doc[p_idx]
                            
                            from src.core.config import root_dir
                            abs_temp_dir = os.path.join(root_dir, "uploads/temp")
                            os.makedirs(abs_temp_dir, exist_ok=True)
                            
                            import uuid
                            img_path = os.path.join(abs_temp_dir, f"{uuid.uuid4()}_p{p_idx}.jpg")
                            # Khôi phục matrix 2.0x2.0 (tương đương chuẩn 300 DPI) để ảnh sắc nét, text detector bắt đúng nét chữ
                            # và OCR nhanh hơn 1.5x1.5 (tránh vỡ hạt nét chữ gây tăng số lượng box giả)
                            pix = sub_page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0))
                            pix.save(img_path)
                            sub_doc.close()
                            
                            text = None
                            line_count = 0
                            if vision_extract:
                                try:
                                    text = extract_text_with_vision_llm(img_path)
                                    from src.core.config import VISION_LLM_COST
                                    users_repo.increment_extraction_stats(user_id, "document", cost=VISION_LLM_COST)
                                except Exception as v_err:
                                    Log.warning(f"[Worker] Vision LLM RAG thất bại trang {p_idx+1}: {v_err}. Chuyển sang local OCR.")
                            
                            if not text:
                                res, _ = ocr_extract(img_path)
                                if res:
                                    line_count = len(res)
                                    text = "\n".join([line['text'] if isinstance(line, dict) else str(line) for line in res])
                            
                            if os.path.exists(img_path):
                                os.remove(img_path)
                                
                            final_text = text if text and text.strip() else fallback_text
                            p_ocr_time = time.time() - t_page_start
                            Log.info(f"[Worker] 📄 Trang {p_idx+1}/{total_pages}: OCR hoàn tất trong {p_ocr_time:.2f}s ({line_count} dòng trích xuất)")
                            return p_idx, final_text, p_ocr_time
                        except Exception as p_err:
                            p_ocr_time = time.time() - t_page_start
                            Log.error(f"[Worker] ❌ Lỗi khi OCR trang {p_idx+1} ({p_ocr_time:.2f}s): {p_err}")
                            return p_idx, fallback_text, p_ocr_time

                    completed_ocr = 0
                    total_ocr_needed = len(pages_needing_ocr)
                    
                    with ThreadPoolExecutor(max_workers=workers_count) as executor:
                        future_to_page = {
                            executor.submit(process_single_ocr_page, p_info): p_info[0]
                            for p_info in pages_needing_ocr
                        }
                        
                        for future in as_completed(future_to_page):
                            p_idx, p_extracted_text, p_ocr_time = future.result()
                            page_results[p_idx] = {"text": p_extracted_text, "page_num": p_idx + 1}
                            page_ocr_times[p_idx] = p_ocr_time
                            completed_ocr += 1
                            
                            total_processed = native_count + completed_ocr
                            percent = int((total_processed / total_pages) * 100)
                            
                            # Cập nhật tiến trình qua Redis SSE sau mỗi trang (nếu <= 10 trang) hoặc mỗi 5 trang
                            if completed_ocr % 5 == 0 or completed_ocr == total_ocr_needed or total_ocr_needed <= 10:
                                Log.info(f"[Worker] ⏳ Tiến độ PDF '{original_filename}': {total_processed}/{total_pages} trang ({percent}%)")
                                publish_event(user_id, "document_status", {
                                    "document_id": doc_id,
                                    "status": DocStatus.PROCESSING,
                                    "progress": f"{total_processed}/{total_pages}",
                                    "percent": percent,
                                    "message": f"Đang xử lý trang {total_processed}/{total_pages}..."
                                })

                    total_ocr_wall_time = time.time() - ocr_start_time
                    avg_ocr_page = total_ocr_wall_time / total_ocr_needed if total_ocr_needed > 0 else 0.0
                    Log.info(f"[Worker] ⏱️ Hoàn tất OCR {total_ocr_needed}/{total_pages} trang trong {total_ocr_wall_time:.2f}s (Trung bình: {avg_ocr_page:.2f}s/trang)")

                structured_data = [res for res in page_results if res is not None]
            except Exception as e:
                Log.error(f"[Worker] Failed to process PDF: {e}")
                pages = extract_text_from_pdf(file_path)
                structured_data = pages
        elif ext in ['jpg', 'jpeg', 'png', 'bmp']:
            img_ocr_start = time.time()
            text = None
            line_count = 0
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
                    line_count = len(ocr_result)
                    text = "\n".join([line['text'] if isinstance(line, dict) else str(line) for line in ocr_result])
            
            total_ocr_wall_time = time.time() - img_ocr_start
            Log.info(f"[Worker] 📄 Ảnh '{original_filename}': OCR hoàn tất trong {total_ocr_wall_time:.2f}s ({line_count} dòng trích xuất)")
            
            if text:
                structured_data = [{"text": text, "page_num": 1}]
        
        if structured_data:
            # Lưu toàn bộ nội dung văn bản thô vào MongoDB để hỗ trợ reindex sau này
            # mà không cần file gốc
            combined_raw_text = "\n\n".join(
                str(item.get("text", "")) for item in structured_data if isinstance(item.get("text"), str) and str(item.get("text", "")).strip()
            )

            # Tự động tạo tên tài liệu thông minh dựa trên nội dung trích xuất
            from src.modules.rag.llm_service import llm_service
            smart_title = llm_service.generate_title(combined_raw_text, fallback_filename=original_filename)
            Log.info(f"[Worker] Smart title for RAG doc {doc_id}: '{smart_title}' (original: '{original_filename}', Category: '{category}')")

            total_chunks = rag_service.index_text(
                structured_data,
                workspace_id,
                smart_title,
                category=category,
                document_id=str(doc_id)
            )
            # Tính toán thông số tổng kết và thời gian
            total_doc_time = time.time() - start_time
            total_pages_cnt = total_pages if ext == 'pdf' and 'total_pages' in locals() else 1
            ocr_pages_cnt = len(pages_needing_ocr) if ext == 'pdf' and 'pages_needing_ocr' in locals() else (1 if ext in ['jpg', 'jpeg', 'png', 'bmp'] else 0)
            native_pages_cnt = native_count if ext == 'pdf' and 'native_count' in locals() else (1 if ext not in ['pdf', 'jpg', 'jpeg', 'png', 'bmp'] else 0)

            timing_debug = {
                "total_time": f"{total_doc_time:.2f}s",
                "ocr_time": f"{total_ocr_wall_time:.2f}s",
                "total_pages": total_pages_cnt,
                "ocr_pages": ocr_pages_cnt,
                "native_pages": native_pages_cnt,
            }

            documents_repo.update_status(
                doc_id, DocStatus.READY,
                total_chunks=total_chunks,
                raw_text=combined_raw_text,
                filename=smart_title,
                original_filename=original_filename,
                category=category,
                debug=timing_debug,
                total_pages=total_pages_cnt
            )
            publish_event(user_id, "document_status", {
                "document_id": doc_id,
                "status": DocStatus.READY,
                "filename": smart_title,
                "original_filename": original_filename,
                "workspace_id": workspace_id,
                "total_chunks": total_chunks,
                "category": category,
                "total_pages": total_pages_cnt,
                "progress": f"{total_pages_cnt}/{total_pages_cnt}",
                "percent": 100,
                "message": "Hoàn tất xử lý tài liệu",
                "debug": timing_debug
            })

            Log.info(
                f"\n" + "="*75 + "\n"
                f"[Worker] 🏁 HOÀN TẤT XỬ LÝ TÀI LIỆU: '{original_filename}'\n"
                f"  • ID tài liệu           : {doc_id}\n"
                f"  • Tiêu đề thông minh    : {smart_title}\n"
                f"  • Danh mục              : {category or 'Mặc định'}\n"
                f"  • Định dạng tệp         : {ext.upper()}\n"
                f"  • Tổng số trang         : {total_pages_cnt} (Text sẵn: {native_pages_cnt}, OCR: {ocr_pages_cnt})\n"
                f"  • Tổng thời gian OCR    : {total_ocr_wall_time:.2f}s\n"
                f"  • Số chunks RAG         : {total_chunks}\n"
                f"  • TỔNG THỜI GIAN XỬ LÝ  : {total_doc_time:.2f}s\n"
                + "="*75
            )
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
                
                for img_idx, img_p in enumerate(all_images):
                    t = time.time()
                    res, _ = ocr_extract(img_p, img=preprocess_for_ocr(img_p), detect_handwriting=detect_handwriting)
                    page_ocr_time = time.time() - t
                    ocr_results.append(res)
                    ocr_times.append(page_ocr_time)
                    Log.info(f"[Worker-Detect] 📄 Ảnh {img_idx+1}/{len(all_images)}: OCR hoàn tất trong {page_ocr_time:.2f}s ({len(res) if res else 0} dòng)")
                
                total_detect_ocr_time = sum(ocr_times)
                Log.info(f"[Worker-Detect] ⏱️ Tổng thời gian OCR ({len(all_images)} ảnh): {total_detect_ocr_time:.2f}s")
                
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
            
            total_detect_time = time.time() - request_start
            total_imgs = len(all_images) if 'all_images' in locals() and all_images else (len(file_paths) if file_paths else 0)
            ocr_time_display = sum(ocr_times) if 'ocr_times' in locals() and ocr_times else 0.0
            Log.info(
                f"\n" + "="*75 + "\n"
                f"[Worker-Detect] 🏁 HOÀN TẤT NHẬN DIỆN: {doc_type}\n"
                f"  • ID tài liệu           : {doc_id}\n"
                f"  • Provider              : {provider}\n"
                f"  • Tổng số ảnh/trang     : {total_imgs}\n"
                f"  • Tổng thời gian OCR    : {ocr_time_display:.2f}s\n"
                f"  • TỔNG THỜI GIAN XỬ LÝ  : {total_detect_time:.2f}s\n"
                + "="*75
            )
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

