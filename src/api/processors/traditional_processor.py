import time
import os
from flask import jsonify
from src.utils.logger import Log
from src.services.log_service import log_service
from src.utils.cloudinary_utils import cloudinary_service
from src.repositories.users_repository import users_repo
from src.utils.smart_config import get_smart_config
from src.utils.smart_spatial_extractor import SmartSpatialExtractor
from src.utils.ocr_utils import filter_useless_lines
from src.utils.text_cleaner import clean_text_lines

def process_traditional(raw_front, raw_back, timer_info, doc_type="idCard", user_id=None, file_paths=None):
    request_start = timer_info["start"]
    ocr_front_time = timer_info["ocr_front"]
    ocr_back_time = timer_info["ocr_back"]

    Log.info(f"[API] 🧹 Dùng pipeline truyền thống (Spatial Hybrid) cho loại: {doc_type}")

    # Check inputs (can be empty lists)
    if not isinstance(raw_front, list): raw_front = []
    if not isinstance(raw_back, list): raw_back = []

    # NORMALIZATION: Ensure all items are dicts with boxes
    # (Handle legacy raw_text input where items are strings)
    if raw_front and isinstance(raw_front[0], str):
        raw_front = [{'text': s, 'box': [[0,0],[0,0],[0,0],[0,0]], 'score': 1.0} for s in raw_front]
    if raw_back and isinstance(raw_back[0], str):
        raw_back = [{'text': s, 'box': [[0,0],[0,0],[0,0],[0,0]], 'score': 1.0} for s in raw_back]

    # ------------------ BƯỚC 5: FILTER ----------------------
    step_start = time.time()
    filtered_front = filter_useless_lines(raw_front)
    filtered_back = filter_useless_lines(raw_back)
    filter_time = time.time() - step_start
    Log.info(f"[API]    🗑️ Filter xong - {filter_time:.2f}s")

    # ------------------ BƯỚC 8: CLEANING ----------------------
    step_start = time.time()
    # Unified cleaning for all lines (supports dicts now)
    clean_front = clean_text_lines(filtered_front)
    clean_back = clean_text_lines(filtered_back)
    
    clean_time = time.time() - step_start
    Log.info(f"[API]    🧹 Clean xong - {clean_time:.2f}s")

    # ------------------ BƯỚC 9: EXTRACT (SPATIAL FLOW) ----------------------
    step_start = time.time()
    extract_result = {}
    
    # Init Spatial Extractor
    config = get_smart_config(doc_type)
    extractor = SmartSpatialExtractor(config)

    Log.info("[API] 🧠 Strategy: Smart Spatial Extraction (Box-aware)...")
    res_front = extractor.extract(clean_front)
    res_back = extractor.extract(clean_back)
    
    # Merge Logic (Prioritize Front for key fields)
    extract_result = res_back.copy()
    
    front_priority_fields = ["idNumber", "fullName", "dob", "gender", "nationality", "hometown", "address", 
                             "plateNumber", "ownerName", "engineNumber", "chassisNumber", "inspectionNumber"]
    
    for k, v in res_front.items():
        if k in front_priority_fields:
            extract_result[k] = v
        else:
            # For other fields (expiryDate), prefer Front if exists, else keep Back
            if v: extract_result[k] = v

    info_extracted = extract_result
    
    extract_time = time.time() - step_start
    Log.info(f"[API]    📊 Extract xong ({doc_type}) - {extract_time:.2f}s")
    Log.debug(f"[API]    📝 Result: {info_extracted}")

    # ------------------ TỔNG KẾT ----------------------
    total_time = time.time() - request_start

    # Increment user stats after successful extraction
    if user_id:
        users_repo.increment_extraction_stats(user_id, doc_type)
        Log.info(f"[API] 📊 Updated extraction stats for user {user_id}")

    # CLOUDINARY UPLOAD (Optional)
    final_file_paths = file_paths
    
    if cloudinary_service.configured and file_paths:
        Log.info(f"[API] ☁️ Đang upload {len(file_paths)} ảnh lên Cloudinary...")
        try:
            upload_urls = []
            for f_path in file_paths:
                url = cloudinary_service.upload_image(f_path)
                if url: 
                    upload_urls.append(url)
                    Log.info(f"[API] ☁️ Uploaded: {url}")
            
            if len(upload_urls) > 0:
                final_file_paths = upload_urls
                Log.info(f"[API] ☁️ Đã thay thế paths bằng Cloudinary URLs.")
        except Exception as cloud_e:
            Log.error(f"[API] ⚠️ Cloudinary upload failed: {cloud_e}")
    elif not cloudinary_service.configured:
        Log.warning("[API] ☁️ Cloudinary chưa được cấu hình, bỏ qua upload.")

    # Log to DB (Mongo - Logs & Documents)
    document_id = log_service.save_logs(user_id, doc_type, final_file_paths, info_extracted)

    Log.info("[API] 🎉 Trả về kết quả kiểu truyền thống")
    return jsonify({
        "statusCode": 200,
        "message": "Success",
        "document_id": document_id,
        "data": info_extracted,
        "debug": {
            "total_time": f"{total_time:.2f}s",
            "ocr_time": f"{ocr_front_time + ocr_back_time:.2f}s",
            "clean_time": f"{clean_time:.2f}s",
            "extract_time": f"{extract_time:.2f}s",
            "gemini": False,
            "doc_type": doc_type,
            "ocr_raw": {
                "front": raw_front,
                "back": raw_back
            },
            "cleaned_lines": {
                "front": clean_front,
                "back": clean_back
            }
        }
    })
