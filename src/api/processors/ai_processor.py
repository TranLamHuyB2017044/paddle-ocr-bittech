import time
import os
from flask import jsonify
from src.utils.logger import Log
from src.services.log_service import log_service
from src.utils.cloudinary_utils import cloudinary_service
from src.repositories.users_repository import users_repo
from src.extractors.grok_extractor import grok_extractor
from src.extractors.gemini_extractor import gemini_extractor
from src.utils.grok_limiter import grok_limiter
from src.utils.gemini_limiter import gemini_limiter
from src.utils.background_tasks import run_background_upload_and_log

def process_with_grok(raw_front, raw_back, timer_info, doc_type, user_id=None, file_paths=None):
    request_start = timer_info["start"]
    ocr_front_time = timer_info["ocr_front"]
    ocr_back_time = timer_info["ocr_back"]
    
    Log.info(f"[API] 🤖 Dùng Grok ({doc_type}) → bỏ qua toàn bộ bước lọc/clean/regex")
    # Normalize input
    flat_front = [x['text'] if isinstance(x, dict) else str(x) for x in raw_front]
    flat_back = [x['text'] if isinstance(x, dict) else str(x) for x in raw_back]
    
    try:
        raw_text = flat_front + flat_back
        
        # --- LOG OCR TEXT ---
        Log.info("\n" + "="*30)
        Log.info("📜 OCR RAW TEXT FOR GROK:")
        for line in raw_text:
            Log.info(f"   {line}")
        Log.info("="*30 + "\n")
        # --------------------

        extraction_result = grok_extractor.extract(raw_text, doc_type=doc_type)
        
        info = extraction_result.get("data", {})
        metadata = extraction_result.get("metadata", {})

        # --- LOG EXTRACTED DATA ---
        Log.info("\n" + "="*30)
        Log.info("🧠 GROK EXTRACTED DATA:")
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

        Log.info("[API] 🎉 Trả về kết quả Grok (Background Upload active)")
        return {
            "statusCode": 200,
            "message": "Success (Grok)",
            "data": info,
            "debug": {
                "total_time": f"{total_time:.2f}s",
                "ocr_time": f"{ocr_front_time + ocr_back_time:.2f}s",
                "provider": "grok",
                "doc_type": doc_type,
                "grok_metadata": metadata,
                "ocr_raw": {
                    "front": raw_front,
                    "back": raw_back
                }
            }
        }
    except Exception as e:
        Log.error(f"[API] ⚠️ API Grok Error: {e}")
        grok_limiter.record_error(e)
        
        error_str = str(e)
        # Check for Quota/Rate Limit (429) or Service Unavailable or Overloaded
        if "429" in error_str or "quota" in error_str or "too many requests" in error_str or "503" in error_str:
             Log.warning("[API] 🛑 Grok Overloaded/RateLimited. Fallback initiated.")
             return None # Signal fallback
        
        # If blocked by limiter
        if grok_limiter.is_blocked():
             Log.warning(f"[API] 🛑 Grok blocked ({grok_limiter.get_remaining_time():.0f}s). Fallback initiated.")
             return None

        raise e

def process_with_gemini(raw_front, raw_back, timer_info, doc_type, user_id=None, file_paths=None):
    request_start = timer_info["start"]
    ocr_front_time = timer_info["ocr_front"]
    ocr_back_time = timer_info["ocr_back"]
    
    Log.info(f"[API] 🤖 Dùng Gemini ({doc_type}) → bỏ qua toàn bộ bước lọc/clean/regex")
    # Normalize input for Gemini (extract text from dicts if needed)
    flat_front = [x['text'] if isinstance(x, dict) else str(x) for x in raw_front]
    flat_back = [x['text'] if isinstance(x, dict) else str(x) for x in raw_back]
    
    try:
        raw_text = flat_front + flat_back
        
        # --- LOG OCR TEXT ---
        Log.info("\n" + "="*30)
        Log.info("📜 OCR RAW TEXT FOR GEMINI:")
        for line in raw_text:
            Log.info(f"   {line}")
        Log.info("="*30 + "\n")
        # --------------------

        extraction_result = gemini_extractor.extract(raw_text, doc_type=doc_type)
        
        info = extraction_result.get("data", {})
        metadata = extraction_result.get("metadata", {})

        # --- LOG EXTRACTED DATA ---
        Log.info("\n" + "="*30)
        Log.info("🧠 GEMINI EXTRACTED DATA:")
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

        Log.info("[API] 🎉 Trả về kết quả Gemini (Background Upload active)")
        return {
            "statusCode": 200,
            "message": "Success (Gemini)",
            "data": info,
            "debug": {
                "total_time": f"{total_time:.2f}s",
                "ocr_time": f"{ocr_front_time + ocr_back_time:.2f}s",
                "gemini": True,
                "doc_type": doc_type,
                "gemini_metadata": metadata,
                "ocr_raw": {
                    "front": raw_front,
                    "back": raw_back
                }
            }
        }
    except Exception as e:
        Log.error(f"[API] ⚠️ API Gemini Error: {e}")
        gemini_limiter.record_error(e)
        
        error_str = str(e)
        # Check for Overloaded (503) or Rate Limit (429) or Service Unavailable
        if "503" in error_str or "429" in error_str or "UNAVAILABLE" in error_str or "overloaded" in error_str:
             Log.warning("[API] 🛑 API Overloaded/RateLimited. Fallback to traditional immediately.")
             return None # Signal fallback
        
        if gemini_limiter.is_blocked():
             Log.warning("[API] 🛑 Fallback to traditional (Circuit Breaker Open).")
             return None # Signal fallback

        Log.error("[API] ❌ Critical Error. Returning error to user.")
        raise e
