import time
import os
from flask import jsonify
from src.utils.logger import Log
from src.services.log_service import log_service
from src.utils.cloudinary_utils import cloudinary_service
from src.repositories.users_repository import users_repo
from src.extractors.openai_extractor import openai_extractor
from src.utils.background_tasks import run_background_upload_and_log
from src.utils.post_cleaner import PostCleaner

def process_with_openai(raw_front, raw_back, timer_info, doc_type, user_id=None, file_paths=None, document_id=None):
    """
    Trích xuất bằng OpenAI từ dữ liệu text đã có (ưu tiên tốc độ - xử lý tuần tự)
    """
    request_start = timer_info["start"]
    ocr_front_time = timer_info["ocr_front"]
    ocr_back_time = timer_info["ocr_back"]
    
    Log.info(f"[API] 🤖 Dùng OpenAI ({doc_type}) - Extraction only")
    
    # Normalize input
    flat_front = [x['text'] if isinstance(x, dict) else str(x) for x in raw_front]
    flat_back = [x['text'] if isinstance(x, dict) else str(x) for x in raw_back]
    combined_text = flat_front + flat_back
    
    try:
        # --- LOG INPUT TEXT ---
        Log.info("\n" + "="*30 + "\n📜 INPUT TEXT FOR OPENAI:\n" + "\n".join([f"   {l}" for l in combined_text]) + "\n" + "="*30)

        extraction_result = openai_extractor.extract(combined_text, doc_type=doc_type)
        
        info = extraction_result.get("data", {})
        metadata = extraction_result.get("metadata", {})

        # --- FINAL CLEANUP (Normalization) ---
        info = PostCleaner.clean(info, doc_type=doc_type)

        total_time = time.time() - request_start
        
        # Inject metadata for logging repo
        if not isinstance(metadata, dict):
            metadata = {}
        metadata["total_time"] = f"{total_time:.2f}s"
        metadata["provider"] = "openai"

        # Increment user stats
        if user_id:
            users_repo.increment_extraction_stats(user_id, doc_type)
            
        # Trigger Background Upload and Logging
        run_background_upload_and_log(user_id, doc_type, file_paths, info, metadata=metadata, document_id=document_id)

        import json
        Log.info(f"[API] 🎁 FINAL OUTPUT ({doc_type}):\n{json.dumps(info, ensure_ascii=False, indent=2)}")
        Log.info("[API] 🎉 Trả về kết quả OpenAI")

        return {
            "statusCode": 200,
            "message": "Success (OpenAI)",
            "data": info,
            "debug": {
                "total_time": f"{total_time:.2f}s",
                "ocr_time": f"{ocr_front_time + ocr_back_time:.2f}s",
                "provider": "openai",
                "doc_type": doc_type,
                "openai_metadata": metadata,
                "ocr_raw": {"front": raw_front, "back": raw_back}
            }
        }
    except Exception as e:
        Log.error(f"[API] ⚠️ API OpenAI Error: {e}")
        import traceback
        Log.error(traceback.format_exc())
        return None
