import os
import traceback
import time
from src.repositories.documents_repository import documents_repo
from src.repositories.users_repository import users_repo
from src.rag.rag_service import rag_service
from src.utils.ocr_utils import ocr_extract, layout_ocr_extract, preprocess_for_ocr
from src.utils.pdf_utils import extract_text_from_pdf, get_pdf_pages_as_images
from src.utils.word_utils import extract_text_from_word
from src.utils.logger import Log
from src.api.processors.ai_processor import process_with_openai
from src.api.processors.traditional_processor import process_traditional
from src.utils.redis_client import publish_event, redis_conn
from src.utils.file_utils import calculate_files_hash
from src.utils.post_cleaner import PostCleaner
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
                        page_text = "\n".join([line['text'] if isinstance(line, dict) else str(line) for line in res])
                        structured_data.append({"text": page_text, "page_num": idx + 1})
                    if os.path.exists(img_p): os.remove(img_p)
            else:
                structured_data = pages
        elif ext in ['jpg', 'jpeg', 'png', 'bmp']:
            ocr_result, _ = ocr_extract(file_path)
            if ocr_result:
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
            run_background_upload_and_log(user_id, doc_type, file_paths, manual_data, document_id=doc_id)
            
            documents_repo.update_status(doc_id, DocStatus.READY, result=manual_data, debug={"total_time": f"{total_time:.2f}s", "provider": "manual_kie"})
            publish_event(user_id, "detection_status", {"document_id": doc_id, "status": DocStatus.READY, "type": doc_type, "result": manual_data, "debug": {"provider": "manual_kie"}})
            return

        # 2. Cache Check
        files_hash = calculate_files_hash(file_paths, raw_text=raw_text)
        cache_key = f"cache:extract:{doc_type}:{provider}:{files_hash}"
        if files_hash:
            cached_result = redis_conn.get(cache_key)
            if cached_result:
                try:
                    res_data = json.loads(cached_result)
                    
                    # Quota increment even for cache hit
                    if user_id:
                        users_repo.increment_extraction_stats(user_id, doc_type)
                        Log.info(f"[Worker-Detect] ⚡ Cache Hit & Quota incremented (User: {user_id})")
                        
                        # LOG even on cache hit for history and "today_extractions" stat
                        from src.utils.background_tasks import run_background_upload_and_log
                        run_background_upload_and_log(user_id, doc_type, file_paths, res_data.get("data"), document_id=doc_id)
                        
                    documents_repo.update_status(doc_id, DocStatus.READY, result=res_data.get("data"), debug={**res_data.get("debug", {}), "cached": True})
                    publish_event(user_id, "detection_status", {"document_id": doc_id, "status": DocStatus.READY, "type": doc_type, "result": res_data.get("data"), "debug": {"cached": True}})
                    return
                except: pass

        # 3. Source Stage (Sequential XOR: raw_text OR OCR)
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
            p1 = file_paths[0]
            t = time.time()
            raw_front, _ = ocr_extract(p1, img=preprocess_for_ocr(p1))
            ocr_front_time = time.time() - t
            
            if len(file_paths) > 1:
                p2 = file_paths[1]
                t = time.time()
                raw_back, _ = ocr_extract(p2, img=preprocess_for_ocr(p2))
                ocr_back_time = time.time() - t
        else:
            raise Exception("No input source (text or image) provided")

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
            if files_hash: redis_conn.setex(cache_key, 86400, json.dumps({"data": result_response.get("data"), "debug": result_response.get("debug")}))
        else:
            raise Exception("Processing failed to return result")
            
    except Exception as e:
        Log.error(f"[Worker-Detect] Failed: {e}")
        documents_repo.update_status(doc_id, DocStatus.FAILED, error_message=str(e))
        publish_event(user_id, "detection_status", {"document_id": doc_id, "status": DocStatus.FAILED, "type": doc_type, "error": str(e)})
    finally:
        if 'file_paths' in locals() and file_paths: silent_cleanup_files(file_paths)
