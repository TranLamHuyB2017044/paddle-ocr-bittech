import os
import traceback
import time
from src.repositories.documents_repository import documents_repo
from src.repositories.users_repository import users_repo
from src.rag.rag_service import rag_service
from src.utils.ocr_utils import ocr_extract, preprocess_for_ocr
from src.utils.pdf_utils import extract_text_from_pdf, get_pdf_pages_as_images
from src.utils.word_utils import extract_text_from_word
from src.utils.logger import Log
from src.api.processors.ai_processor import process_with_openai
from src.api.processors.traditional_processor import process_traditional
from src.utils.redis_client import publish_event, redis_conn
from src.utils.file_utils import calculate_files_hash
from src.utils.post_cleaner import PostCleaner
from src.utils.text_cleaner import clean_text_lines
from src.utils.text_normalizer import normalize_document_text
from src.extractors.document_check_extractor import document_check_extractor
from src.config import DocStatus
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

def process_detection_task(doc_id, user_id, doc_type, file_paths, provider, raw_text=None):
    """
    Background task to process document detection.
    Ưu tiên tuyệt đối raw_text nếu có để đảm bảo tốc độ.
    """
    try:
        Log.info(f"[Worker-Detect] Starting detection: {doc_type} (Provider: {provider})")
        documents_repo.update_status(doc_id, DocStatus.PROCESSING)
        publish_event(user_id, "detection_status", {"document_id": doc_id, "status": DocStatus.PROCESSING, "type": doc_type})
        
        request_start = time.time()
        
        # 1. Manual KIE Fast Path (Specific for CCCD/DriverLicense if raw_text format matches)
        manual_data = None
        if raw_text:
            if doc_type == 'idCard' and '|' in raw_text:
                Log.info("[Worker-Detect] ⚡ Manual KIE Fast-Path activated for CCCD")
                manual_data = PostCleaner.extract_cccd_manual(raw_text)
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
            from src.utils.background_tasks import run_background_upload_and_log
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
                for img_p in all_images:
                    t = time.time()
                    res, _ = ocr_extract(img_p, img=preprocess_for_ocr(img_p))
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
        if provider != 'traditional':
            try:
                result_response = process_with_openai(raw_front, raw_back, timer_info, doc_type, user_id, file_paths, document_id=doc_id)
            except Exception as e:
                Log.error(f"[Worker-Detect] OpenAI failed: {e}")

        if result_response is None or provider == 'traditional':
            result_response = process_traditional(raw_front, raw_back, timer_info, doc_type, user_id, file_paths, document_id=doc_id)

        # 5. Completion
        if result_response:
            documents_repo.update_status(doc_id, DocStatus.READY, result=result_response.get("data"), debug=result_response.get("debug"))
            publish_event(user_id, "detection_status", {"document_id": doc_id, "status": DocStatus.READY, "type": doc_type, "result": result_response.get("data"), "debug": result_response.get("debug")})
            pass # No caching needed
        else:
            raise Exception("Processing failed to return result")
            
    except Exception as e:
        Log.error(f"[Worker-Detect] Failed: {e}")
        documents_repo.update_status(doc_id, DocStatus.FAILED, error_message=str(e))
        publish_event(user_id, "detection_status", {"document_id": doc_id, "status": DocStatus.FAILED, "type": doc_type, "error": str(e)})
        
        # Push error log to database and upload to Cloudinary for debugging
        try:
            from src.utils.background_tasks import run_background_upload_and_log
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
def process_document_check_task(doc_id, user_id, file_path, company_schema, doc_type="invoice"):
    """
    Background task to process document checking against a schema.
    """
    try:
        Log.info(f"[Worker-Check] Starting document check: {doc_id} (Type: {doc_type})")
        documents_repo.update_status(doc_id, DocStatus.PROCESSING)
        publish_event(user_id, "detection_status", {"document_id": doc_id, "status": DocStatus.PROCESSING, "type": "check-document"})
        
        filename = os.path.basename(file_path).lower()
        ext = filename.split('.')[-1]
        
        all_blocks = [] # List of {"page": int, "line": int, "bbox": list, "text": str}
        
        # 1. Extraction Stage
        if ext in ['docx', 'doc']:
            from src.utils.word_utils import extract_lines_from_word
            all_blocks = extract_lines_from_word(file_path)
        elif ext == 'pdf':
            from src.utils.pdf_utils import is_pdf_scanned, extract_text_with_bboxes_from_pdf, get_pdf_pages_as_images
            if is_pdf_scanned(file_path):
                Log.info(f"[Worker-Check] PDF '{filename}' is scanned, using OCR...")
                image_paths = get_pdf_pages_as_images(file_path)
                for idx, img_p in enumerate(image_paths):
                    ocr_res, _ = ocr_extract(img_p)
                    for line_idx, line in enumerate(ocr_res):
                        # Convert [[x,y], [x,y], [x,y], [x,y]] to [x1, y1, x2, y2]
                        box = line["box"]
                        x_min = min(p[0] for p in box)
                        y_min = min(p[1] for p in box)
                        x_max = max(p[0] for p in box)
                        y_max = max(p[1] for p in box)
                        
                        all_blocks.append({
                            "page": idx + 1,
                            "line": line_idx + 1,
                            "bbox": [x_min, y_min, x_max, y_max],
                            "text": line["text"]
                        })
                    if os.path.exists(img_p): os.remove(img_p)
            else:
                all_blocks = extract_text_with_bboxes_from_pdf(file_path)
        elif ext in ['jpg', 'jpeg', 'png', 'bmp']:
            ocr_res, _ = ocr_extract(file_path)
            for line_idx, line in enumerate(ocr_res):
                box = line["box"]
                x_min = min(p[0] for p in box)
                y_min = min(p[1] for p in box)
                x_max = max(p[0] for p in box)
                y_max = max(p[1] for p in box)
                
                all_blocks.append({
                    "page": 1,
                    "line": line_idx + 1,
                    "bbox": [x_min, y_min, x_max, y_max],
                    "text": line["text"]
                })
        else:
            raise Exception(f"Unsupported file format: {ext}")

        if not all_blocks:
            raise Exception("No text could be extracted from the document.")

        # 2. Normalization & Formatting
        for block in all_blocks:
            block["text"] = normalize_document_text(block["text"])

        # 3. Chunking & GPT processing
        # Group by pages
        pages_to_blocks = {}
        for block in all_blocks:
            p = block["page"]
            if p not in pages_to_blocks: pages_to_blocks[p] = []
            pages_to_blocks[p].append(block)
        
        max_pages = max(pages_to_blocks.keys()) if pages_to_blocks else 0
        chunk_size = 5
        final_errors = []
        final_warnings = []
        total_summary = {
            "total_errors": 0,
            "error_breakdown": { "TYPO":0, "NUMBER_MISMATCH":0, "NAME_MISMATCH":0,
                                 "ADDRESS_MISMATCH":0, "MISSING_INFO":0, "DATE_MISMATCH":0 }
        }
        token_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0
        }
        
        for i in range(1, max_pages + 1, chunk_size):
            chunk_blocks = []
            for p_idx in range(i, min(i + chunk_size, max_pages + 1)):
                if p_idx in pages_to_blocks:
                    chunk_blocks.extend(pages_to_blocks[p_idx])
            
            if not chunk_blocks: continue
            
            # Format block strings
            block_strings = []
            for b in chunk_blocks:
                # b['bbox'] is [x1, y1, x2, y2]
                bbox = b.get('bbox')
                if bbox and isinstance(bbox, list) and len(bbox) == 4:
                    bbox_str = f"({bbox[0]:.1f},{bbox[1]:.1f},{bbox[2]:.1f},{bbox[3]:.1f})"
                else:
                    bbox_str = "null"
                
                block_strings.append(f"[Trang {b['page']} | Dòng {b['line']} | bbox:{bbox_str}] {b['text']}")
            
            blocks_text = "\n".join(block_strings)
            
            # Call GPT
            resp, usage = document_check_extractor.check_document(blocks_text, company_schema, doc_type)
            
            if usage:
                token_usage["prompt_tokens"] += getattr(usage, "prompt_tokens", 0)
                token_usage["completion_tokens"] += getattr(usage, "completion_tokens", 0)
                token_usage["total_tokens"] += getattr(usage, "total_tokens", 0)

            if resp:
                final_errors.extend(resp.get("errors", []))
                final_warnings.extend(resp.get("warnings", []))
                
                # Update summary
                chunk_sum = resp.get("summary", {})
                total_summary["total_errors"] += chunk_sum.get("total_errors", 0)
                br = chunk_sum.get("error_breakdown", {})
                for k, v in br.items():
                    if k in total_summary["error_breakdown"]:
                        total_summary["error_breakdown"][k] += v

        # Combine results
        merged_result = {
            "status": "FAIL" if total_summary["total_errors"] > 0 else "PASS",
            "summary": total_summary,
            "errors": final_errors,
            "warnings": final_warnings,
            "metadata": {
                "token_usage": token_usage
            }
        }
        
        Log.info(f"[Worker-Check] ✅ Check completed. Usage: {token_usage['total_tokens']} tokens")

        # 4. Completion
        documents_repo.update_status(doc_id, DocStatus.READY, result=merged_result)
        publish_event(user_id, "detection_status", {"document_id": doc_id, "status": DocStatus.READY, "type": "check-document", "result": merged_result})
        
    except Exception as e:
        Log.error(f"[Worker-Check] Failed: {e}")
        traceback.print_exc()
        documents_repo.update_status(doc_id, DocStatus.FAILED, error_message=str(e))
        publish_event(user_id, "detection_status", {"document_id": doc_id, "status": DocStatus.FAILED, "type": "check-document", "error": str(e)})
    finally:
        if 'file_path' in locals() and file_path: silent_cleanup_files(file_path)
