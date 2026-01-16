import os
import traceback
import time
from src.repositories.documents_repository import documents_repo
from src.rag.rag_service import rag_service
from src.utils.ocr_utils import ocr_extract, layout_ocr_extract, filter_back_side_lines, preprocess_for_ocr
from src.utils.pdf_utils import extract_text_from_pdf, get_pdf_pages_as_images
from src.utils.word_utils import extract_text_from_word
from src.utils.logger import Log
from src.api.processors.ai_processor import process_with_grok, process_with_gemini
from src.api.processors.traditional_processor import process_traditional
from src.utils.redis_client import publish_event, redis_conn
from src.utils.file_utils import calculate_files_hash
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
                    # Use debug level to be "silent"
                    Log.debug(f"[Cleanup] 🗑️ Removed: {path}")
                except Exception as e:
                    Log.debug(f"[Cleanup] ❌ Failed to delete {path}: {e}")
    
    thread = threading.Thread(target=cleanup, daemon=True)
    thread.start()

def process_document_task(doc_id, workspace_id, file_path, original_filename, user_id):
    """
    Background task to process OCR, extraction and indexing for RAG
    """
    try:
        start_time = time.time()
        Log.info(f"[Worker] Starting processing document: {original_filename} (ID: {doc_id})")
        
        # 1. Update status to PROCESSING
        documents_repo.update_status(doc_id, DocStatus.PROCESSING)
        publish_event(user_id, "document_status", {
            "document_id": doc_id,
            "status": DocStatus.PROCESSING,
            "filename": original_filename
        })
        
        ext = original_filename.lower().split('.')[-1]
        full_text = ""
        
        # 2. Extract Text (Heavy CPU work)
        if ext == 'md':
            with open(file_path, 'r', encoding='utf-8') as f:
                full_text = f.read()
        
        elif ext in ['docx', 'doc']:
            full_text = extract_text_from_word(file_path)
            
        elif ext == 'pdf':
            full_text = extract_text_from_pdf(file_path)
            # If no text (scanned), use OCR
            if not full_text.strip():
                image_paths = get_pdf_pages_as_images(file_path)
                ocr_texts = []
                for img_p in image_paths:
                    res, _ = ocr_extract(img_p)
                    if res:
                        page_text = "\n".join([line['text'] if isinstance(line, dict) else str(line) for line in res])
                        ocr_texts.append(page_text)
                    if os.path.exists(img_p): os.remove(img_p)
                full_text = "\n\n".join(ocr_texts)
                
        elif ext in ['jpg', 'jpeg', 'png', 'bmp']:
            ocr_result, _ = ocr_extract(file_path)
            if ocr_result:
                full_text = "\n".join([line['text'] if isinstance(line, dict) else str(line) for line in ocr_result])
        
        # 3. Indexing (Embedding + Qdrant)
        if full_text.strip():
            total_chunks = rag_service.index_text(full_text, workspace_id, original_filename)
            
            # 4. Success -> Mark as READY
            documents_repo.update_status(doc_id, DocStatus.READY, total_chunks=total_chunks)
            publish_event(user_id, "document_status", {
                "document_id": doc_id,
                "status": DocStatus.READY,
                "filename": original_filename,
                "total_chunks": total_chunks,
                "debug": {
                    "total_time": f"{time.time() - start_time:.2f}s" if 'start_time' in locals() else "N/A"
                }
            })
            Log.info(f"[Worker] Successfully processed: {original_filename} - Total time: {time.time() - start_time:.2f}s")
        else:
            raise Exception("No text could be extracted from this document")
            
    except Exception as e:
        error_msg = str(e)
        Log.error(f"[Worker] Failed to process {original_filename}: {error_msg}")
        Log.error(traceback.format_exc())
        documents_repo.update_status(doc_id, DocStatus.FAILED, error_message=error_msg)
        publish_event(user_id, "document_status", {
            "document_id": doc_id,
            "status": DocStatus.FAILED,
            "filename": original_filename,
            "error": error_msg
        })
        
    finally:
        # 6. Cleanup file (Silently in background)
        if 'file_path' in locals():
            silent_cleanup_files(file_path)

def process_detection_task(doc_id, user_id, doc_type, file_paths, provider="grok", raw_text=None):
    """
    Background task to process document detection (ID Card, License, etc.)
    """
    try:
        Log.info(f"[Worker-Detect] Starting detection: {doc_type} (ID: {doc_id})")
        
        # 1. Update status to PROCESSING
        documents_repo.update_status(doc_id, DocStatus.PROCESSING)
        publish_event(user_id, "detection_status", {
            "document_id": doc_id,
            "status": DocStatus.PROCESSING,
            "type": doc_type
        })
        
        request_start = time.time()
        
        # 2. Cache Check
        files_hash = calculate_files_hash(file_paths)
        cache_key = f"cache:extract:{doc_type}:{provider}:{files_hash}"
        
        if files_hash:
            cached_result = redis_conn.get(cache_key)
            if cached_result:
                try:
                    result_data = json.loads(cached_result)
                    Log.info(f"[Worker-Detect] ⚡ Cache Hit! Returning cached result for hash {files_hash}")
                    
                    # Update status and send SSE
                    documents_repo.update_status(
                        doc_id, DocStatus.READY, 
                        result=result_data.get("data"), 
                        debug={**result_data.get("debug", {}), "cached": True}
                    )
                    publish_event(user_id, "detection_status", {
                        "document_id": doc_id,
                        "status": DocStatus.READY,
                        "type": doc_type,
                        "result": result_data.get("data"),
                        "debug": {**result_data.get("debug", {}), "cached": True}
                    })
                    return # Exit task early
                except Exception as cache_err:
                    Log.error(f"[Worker-Detect] ⚠️ Failed to parse cache: {cache_err}")

        # 3. OCR (Heaviest part)
        raw_front = []
        raw_back = []
        ocr_front_time = 0.0
        ocr_back_time = 0.0
        
        if raw_text:
            Log.info(f"[Worker-Detect] � Using provided raw_text (Skipping OCR)")
            for line in raw_text.split('\n'):
                if line.strip():
                    raw_front.append({"text": line.strip(), "box": [[0,0],[0,0],[0,0],[0,0]], "score": 1.0})
        elif len(file_paths) > 0:
            p1 = file_paths[0]
            t = time.time()
            img1 = preprocess_for_ocr(p1)
            raw_front, _ = ocr_extract(p1, img=img1)
            ocr_front_time = time.time() - t
            
        if len(file_paths) > 1:
            p2 = file_paths[1]
            t = time.time()
            img2 = preprocess_for_ocr(p2)
            raw_back_all, _ = ocr_extract(p2, img=img2)
            if doc_type == 'idCard':
                Log.info("[Worker-Detect] 🛡️ Applying Back Side Keyword Filter for ID Card")
                raw_back = filter_back_side_lines(raw_back_all)
            else:
                raw_back = raw_back_all
            ocr_back_time = time.time() - t
            
        timer_info = {
            "start": request_start,
            "ocr_front": ocr_front_time,
            "ocr_back": ocr_back_time
        }
        
        # 3. Process with UI Processors (with Fallback Logic)
        result_response = None
        current_provider = provider
        
        Log.info(f"[Worker-Detect] 🎯 Initial provider selected: {current_provider}")
        
        # --- PHASE 1: Try Primary Provider ---
        try:
            if current_provider == 'grok':
                result_response = process_with_grok(raw_front, raw_back, timer_info, doc_type, user_id, file_paths)
            elif current_provider == 'gemini':
                result_response = process_with_gemini(raw_front, raw_back, timer_info, doc_type, user_id, file_paths)
        except Exception as e:
            Log.error(f"[Worker-Detect] ❌ Primary Provider ({current_provider}) Critical Error: {e}")
            result_response = None # Force fallback if exception occurred but wasn't caught inside
            
        # --- PHASE 2: Fallback to Gemini if Grok failed ---
        if current_provider == 'grok' and result_response is None:
            Log.warning("[Worker-Detect] 🔄 Grok failed/overloaded. Falling back to Gemini...")
            current_provider = 'gemini'
            try:
                result_response = process_with_gemini(raw_front, raw_back, timer_info, doc_type, user_id, file_paths)
            except Exception as e:
                Log.error(f"[Worker-Detect] ❌ Fallback Gemini Critical Error: {e}")
                result_response = None

        # --- PHASE 3: Fallback to Traditional if all AI failed or if Traditional was requested ---
        if result_response is None or current_provider == 'traditional':
            reason = "AIs failed" if result_response is None and current_provider != 'traditional' else "requested"
            Log.warning(f"[Worker-Detect] 🔄 Switching to Traditional pipeline (Reason: {reason})...")
            current_provider = 'traditional'
            result_response = process_traditional(raw_front, raw_back, timer_info, doc_type, user_id, file_paths)
            
        # 4. Success -> Mark as READY and store result
        if result_response:
            final_provider = result_response.get("debug", {}).get("provider", current_provider)
            Log.info(f"[Worker-Detect] ✅ SUCCESS! Final provider used: {final_provider}")
            
            documents_repo.update_status(
                doc_id, DocStatus.READY, 
                result=result_response.get("data"), 
                debug=result_response.get("debug")
            )
            publish_event(user_id, "detection_status", {
                "document_id": doc_id,
                "status": DocStatus.READY,
                "type": doc_type,
                "result": result_response.get("data"),
                "debug": result_response.get("debug")
            })
            # 5. Save to Cache
            if files_hash:
                try:
                    cache_payload = {
                        "data": result_response.get("data"),
                        "debug": result_response.get("debug")
                    }
                    # Cache for 24 hours (86400 seconds)
                    redis_conn.setex(cache_key, 86400, json.dumps(cache_payload))
                    Log.info(f"[Worker-Detect] 💾 Result cached with key: {cache_key}")
                except Exception as cache_save_err:
                    Log.error(f"[Worker-Detect] ⚠️ Could not save to cache: {cache_save_err}")

            Log.info(f"[Worker-Detect] 📑 Detection task completed for {doc_type}")
        else:
            Log.error("[Worker-Detect] ❌ Final extraction failed - No result from any provider")
            raise Exception("Processing failed to return valid data after trying all providers")
            
    except Exception as e:
        error_msg = str(e)
        Log.error(f"[Worker-Detect] Failed: {error_msg}")
        Log.error(traceback.format_exc())
        documents_repo.update_status(doc_id, DocStatus.FAILED, error_message=error_msg)
        publish_event(user_id, "detection_status", {
            "document_id": doc_id,
            "status": DocStatus.FAILED,
            "type": doc_type,
            "error": error_msg
        })
    finally:
        # 5. Cleanup files (Silently in background)
        if 'file_paths' in locals() and file_paths:
            silent_cleanup_files(file_paths)
