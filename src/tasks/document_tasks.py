import os
import traceback
import time
from src.repositories.documents_repository import documents_repo
from src.rag.rag_service import rag_service
from src.utils.ocr_utils import ocr_extract
from src.utils.pdf_utils import extract_text_from_pdf, get_pdf_pages_as_images
from src.utils.word_utils import extract_text_from_word
from src.utils.logger import Log
from src.api.processors.ai_processor import process_with_grok, process_with_gemini
from src.api.processors.traditional_processor import process_traditional

def process_document_task(doc_id, workspace_id, file_path, original_filename):
    """
    Background task to process OCR, extraction and indexing for RAG
    """
    try:
        Log.info(f"[Worker] Starting processing document: {original_filename} (ID: {doc_id})")
        
        # 1. Update status to PROCESSING
        documents_repo.update_status(doc_id, "PROCESSING")
        
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
            documents_repo.update_status(doc_id, "READY", total_chunks=total_chunks)
            Log.info(f"[Worker] Successfully processed: {original_filename}")
        else:
            raise Exception("No text could be extracted from this document")
            
    except Exception as e:
        error_msg = str(e)
        Log.error(f"[Worker] Failed to process {original_filename}: {error_msg}")
        Log.error(traceback.format_exc())
        documents_repo.update_status(doc_id, "FAILED", error_message=error_msg)
        
    finally:
        # 6. Cleanup file
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
                Log.info(f"[Worker] Cleaned up file: {file_path}")
            except Exception as e:
                Log.error(f"[Worker] Failed to delete file {file_path}: {e}")

def process_detection_task(doc_id, user_id, doc_type, file_paths, provider="grok"):
    """
    Background task to process document detection (ID Card, License, etc.)
    """
    try:
        Log.info(f"[Worker-Detect] Starting detection: {doc_type} (ID: {doc_id})")
        
        # 1. Update status to PROCESSING
        documents_repo.update_status(doc_id, "PROCESSING")
        
        request_start = time.time()
        
        # 2. OCR (Heaviest part)
        raw_front = []
        raw_back = []
        ocr_front_time = 0.0
        ocr_back_time = 0.0
        
        if len(file_paths) > 0:
            p1 = file_paths[0]
            t = time.time()
            raw_front, _ = ocr_extract(p1, doc_type=doc_type, side="front")
            ocr_front_time = time.time() - t
            
        if len(file_paths) > 1:
            p2 = file_paths[1]
            t = time.time()
            raw_back, _ = ocr_extract(p2, doc_type=doc_type, side="back")
            ocr_back_time = time.time() - t
            
        timer_info = {
            "start": request_start,
            "ocr_front": ocr_front_time,
            "ocr_back": ocr_back_time
        }
        
        # 3. Process with UI Processors
        result_response = None
        if provider == 'grok':
            result_response = process_with_grok(raw_front, raw_back, timer_info, doc_type, user_id, file_paths)
        elif provider == 'gemini':
            result_response = process_with_gemini(raw_front, raw_back, timer_info, doc_type, user_id, file_paths)
        else:
            result_response = process_traditional(raw_front, raw_back, timer_info, doc_type, user_id, file_paths)
            
        # 4. Success -> Mark as READY and store result
        if result_response:
            # result_response is now a dict (from our refactored processors)
            documents_repo.update_status(
                doc_id, "READY", 
                result=result_response.get("data"), 
                debug=result_response.get("debug")
            )
            Log.info(f"[Worker-Detect] Successfully detected {doc_type}")
        else:
            raise Exception("Processing failed to return valid data")
            
    except Exception as e:
        error_msg = str(e)
        Log.error(f"[Worker-Detect] Failed: {error_msg}")
        Log.error(traceback.format_exc())
        documents_repo.update_status(doc_id, "FAILED", error_message=error_msg)
    finally:
        # 5. Cleanup files
        if file_paths:
            for path in file_paths:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                        Log.info(f"[Worker-Detect] 🗑️ Cleaned up temp file: {path}")
                    except Exception as e:
                        Log.error(f"[Worker-Detect] ❌ Failed to delete file {path}: {e}")
