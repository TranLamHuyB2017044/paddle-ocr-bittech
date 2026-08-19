import time
import os
from flask import jsonify
from src.shared.utils.logger import Log
from src.shared.services.log_service import log_service
from src.shared.utils.cloudinary_utils import cloudinary_service
from src.shared.repositories.users_repository import users_repo
from src.shared.utils.smart_config import get_smart_config
from src.shared.utils.smart_spatial_extractor import SmartSpatialExtractor
from src.shared.utils.ocr_utils import filter_useless_lines
from src.shared.utils.text_cleaner import clean_text_lines
from src.shared.utils.background_tasks import run_background_upload_and_log
from src.shared.utils.post_cleaner import PostCleaner

def process_traditional(raw_front, raw_back, timer_info, doc_type="idCard", user_id=None, file_paths=None, document_id=None):
    request_start = timer_info["start"]
    ocr_front_time = timer_info["ocr_front"]
    ocr_back_time = timer_info["ocr_back"]

    Log.info(f"[API] 🧹 Dùng pipeline truyền thống cho loại: {doc_type}")

    # Check inputs (can be empty lists)
    if not isinstance(raw_front, list): raw_front = []
    if not isinstance(raw_back, list): raw_back = []

    # NORMALIZATION
    if raw_front and isinstance(raw_front[0], str):
        raw_front = [{'text': s, 'box': [[0,0],[0,0],[0,0],[0,0]], 'score': 1.0} for s in raw_front]
    if raw_back and isinstance(raw_back[0], str):
        raw_back = [{'text': s, 'box': [[0,0],[0,0],[0,0],[0,0]], 'score': 1.0} for s in raw_back]

    # --- FILTER (Rules removed in ocr_utils, now returns as-is) ---
    filtered_front = filter_useless_lines(raw_front)
    filtered_back = filter_useless_lines(raw_back)

    # --- CLEANING (Chạy cho invoice, vehicleDocuments và menu) ---
    if doc_type in ['invoice', 'vehicleDocuments', 'menu']:
        clean_front = clean_text_lines(filtered_front)
        clean_back = clean_text_lines(filtered_back)
    else:
        clean_front = filtered_front
        clean_back = filtered_back

    # --- EXTRACTION ---
    step_start = time.time()
    info_extracted = {}
    
    # NEW: Manual KIE logic for ID Card (CCCD) or Driver License
    if doc_type == "idCard":
        Log.info("[API] 🎯 Trích xuất KIE thủ công cho CCCD")
        # Combine both front and back text for comprehensive extraction
        all_clean_lines = clean_front + clean_back
        lines = [x.get("text", "").strip() for x in all_clean_lines if x.get("text", "").strip()]
        joined = "|".join(lines)
        if "|" in joined:
            info_extracted = PostCleaner.extract_cccd_manual(joined)
        
        if not info_extracted and len(lines) >= 6:
            manual_str = "|".join(lines[:6])
            info_extracted = PostCleaner.extract_cccd_manual(manual_str)
            
        if not info_extracted:
            info_extracted = {"note": "Cần tối thiểu 6 trường thông tin (Số, Tên, Ngày sinh, Giới tính, Địa chỉ, Ngày cấp)"}

    elif doc_type == "driverLicense":
        Log.info("[API] 🎯 Trích xuất KIE thủ công cho DriverLicense")
        # Combine both front and back text
        all_clean_lines = clean_front + clean_back
        lines = [x.get("text", "").strip() for x in all_clean_lines if x.get("text", "").strip()]
        
        if len(lines) >= 4:
            # Re-use manual extractor logic via newline join
            info_extracted = PostCleaner.extract_driver_manual("\n".join(lines))
        
        if not info_extracted:
            info_extracted = {"note": "Cần tối thiểu 4 trường thông tin (Số, Tên, Ngày sinh, Hạng)"}

    # Keep Spatial Extractor only for other documents
    else:
        config = get_smart_config(doc_type)
        extractor = SmartSpatialExtractor(config)
        res_front = extractor.extract(clean_front)
        res_back = extractor.extract(clean_back)
        info_extracted = {**res_back, **res_front}

    # Final Post-Clean
    info_extracted = PostCleaner.clean(info_extracted, doc_type=doc_type)
    
    total_time = time.time() - request_start
    if user_id: users_repo.increment_extraction_stats(user_id, doc_type)

    metadata = {
        "total_time": f"{total_time:.2f}s",
        "provider": "traditional"
    }
    run_background_upload_and_log(user_id, doc_type, file_paths, info_extracted, metadata=metadata, document_id=document_id)

    Log.info(f"[API] 🎉 Hoàn tất trích xuất {doc_type}")
    return {
        "statusCode": 200,
        "message": "Success",
        "data": info_extracted,
        "debug": {
            "total_time": f"{total_time:.2f}s",
            "ocr_time": f"{ocr_front_time + ocr_back_time:.2f}s",
            "provider": "traditional_manual" if doc_type == "idCard" else "traditional_spatial",
            "doc_type": doc_type
        }
    }
