import time
import os
from flask import jsonify
from src.utils.logger import Log
from src.services.log_service import log_service
from src.utils.cloudinary_utils import cloudinary_service
from src.repositories.users_repository import users_repo
from src.extractors.openai_extractor import openai_extractor
from src.utils.background_tasks import run_background_upload_and_log

def process_with_openai(raw_front, raw_back, timer_info, doc_type, user_id=None, file_paths=None):
    request_start = timer_info["start"]
    ocr_front_time = timer_info["ocr_front"]
    ocr_back_time = timer_info["ocr_back"]
    
    Log.info(f"[API] 🤖 Dùng OpenAI ({doc_type}) → bỏ qua toàn bộ bước lọc/clean/regex")
    # Normalize input
    flat_front = [x['text'] if isinstance(x, dict) else str(x) for x in raw_front]
    flat_back = [x['text'] if isinstance(x, dict) else str(x) for x in raw_back]
    
    try:
        raw_text = flat_front + flat_back
        
        # --- LOG OCR TEXT ---
        Log.info("\n" + "="*30)
        Log.info("📜 OCR RAW TEXT FOR OPENAI:")
        for line in raw_text:
            Log.info(f"   {line}")
        Log.info("="*30 + "\n")
        # --------------------

        extraction_result = openai_extractor.extract(raw_text, doc_type=doc_type)
        
        info = extraction_result.get("data", {})
        metadata = extraction_result.get("metadata", {})

        # --- LOG EXTRACTED DATA ---
        Log.info("\n" + "="*30)
        Log.info("🧠 OPENAI EXTRACTED DATA:")
        Log.info(str(info))
        Log.info("="*30 + "\n")
        # --------------------------

        total_time = time.time() - request_start

        # Increment user stats after successful extraction
        if user_id:
            users_repo.increment_extraction_stats(user_id, doc_type)
            Log.info(f"[API] 📊 Updated extraction stats for user {user_id}")
            
        # Trigger Background Upload and Logging
        run_background_upload_and_log(user_id, doc_type, file_paths, info, metadata=metadata)

        Log.info("[API] 🎉 Trả về kết quả OpenAI (Background Upload active)")
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
                "ocr_raw": {
                    "front": raw_front,
                    "back": raw_back
                }
            }
        }
    except Exception as e:
        Log.error(f"[API] ⚠️ API OpenAI Error: {e}")
        return None # Signal fallback
