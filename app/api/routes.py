"""
API Routes
Định nghĩa các API endpoints cho CCCD OCR
"""
import time
import os
from datetime import datetime
from flask import request, jsonify

from app.utils.file_utils import allowed_file, save_uploaded_files
from app.utils.ocr_utils import ocr_extract, filter_useless_lines
from app.utils.text_cleaner import clean_text_lines
from app.extractors.gemini_extractor import gemini_extractor
from app.utils.smart_config import smart_extract
from app.utils.post_cleaner import PostCleaner
from app.utils.gemini_limiter import gemini_limiter
from app.utils.logger import Log



ALLOWED_DOC_TYPES = {'idCard', 'driverLicense', 'invoice', 'document'}
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB limit

def process_with_gemini(raw_front, raw_back, timer_info, doc_type):
    request_start = timer_info["start"]
    ocr_front_time = timer_info["ocr_front"]
    ocr_back_time = timer_info["ocr_back"]
    
    Log.info(f"[API] 🤖 Dùng Gemini ({doc_type}) → bỏ qua toàn bộ bước lọc/clean/regex")
    try:
        raw_text = raw_front + raw_back
        extraction_result = gemini_extractor.extract(raw_text, doc_type=doc_type)
        
        info = extraction_result.get("data", {})
        metadata = extraction_result.get("metadata", {})

        total_time = time.time() - request_start

        Log.info("[API] 🎉 Trả về kết quả Gemini")
        return jsonify({
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
        })
    except Exception as e:
        Log.error(f"[API] ⚠️ API Gemini Error: {e}")
        gemini_limiter.record_error(e)
        
        if gemini_limiter.is_blocked():
             Log.warning("[API] 🛑 Fallback to traditional due to RateLimit/Timeout.")
             return None # Signal fallback
        else:
             Log.error("[API] ❌ Critical Error (not rate limit). Returning error to user.")
             raise e

def process_traditional(raw_front, raw_back, timer_info, doc_type="idCard"):
    request_start = timer_info["start"]
    ocr_front_time = timer_info["ocr_front"]
    ocr_back_time = timer_info["ocr_back"]

    Log.info(f"[API] 🧹 Dùng pipeline truyền thống (Hybrid) cho loại: {doc_type}")

    # Check inputs (can be empty lists)
    if not isinstance(raw_front, list): raw_front = []
    if not isinstance(raw_back, list): raw_back = []

    # ------------------ BƯỚC 5: FILTER ----------------------
    step_start = time.time()
    filtered_front = filter_useless_lines(raw_front)
    filtered_back = filter_useless_lines(raw_back)
    filter_time = time.time() - step_start
    Log.info(f"[API]    🗑️ Filter xong - {filter_time:.2f}s")

    # ------------------ BƯỚC 8: CLEANING ----------------------
    step_start = time.time()
    # Unified cleaning for all lines
    clean_front = clean_text_lines(filtered_front)
    clean_back = clean_text_lines(filtered_back)
    
    clean_time = time.time() - step_start
    Log.info(f"[API]    🧹 Clean xong - {clean_time:.2f}s")

    # ------------------ BƯỚC 9: EXTRACT (HYBRID FLOW) ----------------------
    step_start = time.time()
    extract_result = {}
    
    # Priority Strategy:
    # Smart Regex (Rule-based) - Safe fallback & good for specific formats
    
    # Init empty results
    res_front = {}
    res_back = {}

    Log.info("[API] 🧠 Strategy: Smart Regex (Rule-based)...")
    res_front = smart_extract(clean_front, doc_type=doc_type)
    res_back = smart_extract(clean_back, doc_type=doc_type)

    
    extract_result = res_back.copy()
    
    front_priority_fields = ["idNumber", "fullName", "dob", "gender", "nationality", "hometown", "address"]
    
    for k, v in res_front.items():
        if k in front_priority_fields:
            extract_result[k] = v
        else:
            # For other fields (expiryDate), prefer Front if exists, else keep Back
            if v: extract_result[k] = v
            # If front doesn't have it, we keep what's in Back

    extract_result = PostCleaner.clean(extract_result, doc_type)
    
    info_extracted = extract_result
    
    extract_time = time.time() - step_start
    Log.info(f"[API]    📊 Extract xong ({doc_type}) - {extract_time:.2f}s")
    Log.debug(f"[API]    📝 Result: {info_extracted}")

    # ------------------ TỔNG KẾT ----------------------
    total_time = time.time() - request_start

    Log.info("[API] 🎉 Trả về kết quả kiểu truyền thống")
    return jsonify({
        "statusCode": 200,
        "message": "Success",
        "data": info_extracted,
        "debug": {
            "total_time": f"{total_time:.2f}s",
            "ocr_time": f"{ocr_front_time + ocr_back_time:.2f}s",
            # "filter_time": f"{filter_time:.2f}s",
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

def validate_request_params(req):
    """
    Validate request parameters and files
    """
    # 1. Check content length
    if req.content_length and req.content_length > MAX_CONTENT_LENGTH:
        return None, jsonify({"statusCode": 413, "message": f"File quá lớn. Giới hạn {MAX_CONTENT_LENGTH/1024/1024}MB"}), 413

    # 2. Check doc_type
    doc_type = req.form.get("type")
    
    if not doc_type:
        # Enforce strict requirement as per user request: "type bắt buộc trong enum đó"
        return None, jsonify({"statusCode": 400, "message": "Missing 'type' parameter. Required one of: idCard, driverLicense, invoice, document"}), 400

    if doc_type not in ALLOWED_DOC_TYPES:
         return None, jsonify({"statusCode": 400, "message": f"Loại giấy tờ không hợp lệ. Cho phép: {ALLOWED_DOC_TYPES}"}), 400

    return doc_type, None, None

def register_routes(app):
    """
    Đăng ký các routes cho Flask app
    
    Args:
        app: Flask application instance
    """
    
    @app.route("/", methods=["GET"])
    def health_check():
        return jsonify({"status": "ok", "message": "CCCD OCR API is running"}), 200

    @app.route("/api/traditional", methods=["POST"])
    def detect_traditional():
        request_start = time.time()
        p1 = None
        p2 = None

        Log.info("\n" + "#"*70)
        Log.info("###  🚀 TRADITIONAL TEST REQUEST")
        Log.info(f"###  ⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")
        Log.info("#"*70 + "\n")

        try:
            # ==================== BƯỚC 1: VALIDATE ====================
            step_start = time.time()
            Log.info("[API-TRAD] 📋 Bước 1: Validate request...")
            
            # Validate params
            doc_type, error_resp, status_code = validate_request_params(request)
            if error_resp:
                Log.error(f"[API-TRAD] ❌ Validation Failed: {error_resp.json}")
                return error_resp, status_code

            raw_boxes_front = []
            raw_boxes_back = []
            
            # Initialize variables
            raw_front = []
            raw_back = []
            ocr_front_time = 0.0
            ocr_back_time = 0.0

            # 🆕 CHECK: RAW TEXT INPUT (Bypass OCR)
            raw_text_input = request.form.get("raw_text")

            if raw_text_input:
                Log.info("[API-TRAD] 📝 Nhận diện 'raw_text' -> Bỏ qua OCR, xử lý trực tiếp.")
                raw_front = [line.strip() for line in raw_text_input.strip().split('\\n') if line.strip()]
                Log.info(f"[API-TRAD]    📝 Input lines: {len(raw_front)}")
            
            else:
                # 📷 FILE UPLOAD FLOW
                if "first_image" not in request.files and "second_image" not in request.files:
                    return jsonify({"statusCode": 400, "message": "Cần ít nhất 1 file (first_image hoặc second_image) hoặc field 'raw_text'"}), 400

                f1 = request.files.get("first_image")
                f2 = request.files.get("second_image")
                
                Log.info(f"[API-TRAD] ✅ Validation OK (Type: {doc_type}) - {time.time() - step_start:.2f}s")

                # ==================== BƯỚC 2: LƯU FILE ====================
                step_start = time.time()
                Log.info("[API-TRAD] 💾 Bước 2: Lưu file...")
                p1, p2 = save_uploaded_files(f1, f2)
                if p1: Log.info(f"[API-TRAD]    📁 Front: {p1}")
                if p2: Log.info(f"[API-TRAD]    📁 Back: {p2}")
                Log.info(f"[API-TRAD] ✅ Lưu file xong - {time.time() - step_start:.2f}s")

                # ==================== BƯỚC 3: OCR HAI MẶT ====================
                Log.info("[API-TRAD] 🔍 Bước 3: OCR...")

                if p1:
                    t = time.time()
                    raw_front, _ = ocr_extract(p1)
                    ocr_front_time = time.time() - t
                    Log.info(f"[API-TRAD]    ⏳ OCR front: {ocr_front_time:.2f}s")

                if p2:
                    t = time.time()
                    raw_back, _ = ocr_extract(p2)
                    ocr_back_time = time.time() - t
                    Log.info(f"[API-TRAD]    ⏳ OCR back : {ocr_back_time:.2f}s")

            Log.info("[API-TRAD] ✅ OCR xong")
            
            timer_info = {
                "start": request_start,
                "ocr_front": ocr_front_time,
                "ocr_back": ocr_back_time
            }

            # FORCE TRADITIONAL FLOW
            return process_traditional(
                raw_front, raw_back, 
                timer_info, 
                doc_type=doc_type, 
            )

        except Exception as e:
            Log.error("\n" + "!"*70)
            Log.error(f"[API-TRAD] ❌ LỖI: {str(e)}")
            Log.error("!"*70 + "\n")

            return jsonify({
                "statusCode": 500,
                "message": "Lỗi server",
                "error": str(e)
            }), 500
        
        finally:
            # Cleanup uploaded files
            if p1 and os.path.exists(p1):
                try:
                    os.remove(p1)
                    Log.info(f"[CLEANUP] 🗑️ Deleted {p1}")
                except Exception as e:
                    Log.error(f"[CLEANUP] ⚠️ Failed to delete {p1}: {e}")
            
            if p2 and os.path.exists(p2):
                try:
                    os.remove(p2)
                    Log.info(f"[CLEANUP] 🗑️ Deleted {p2}")
                except Exception as e:
                    Log.error(f"[CLEANUP] ⚠️ Failed to delete {p2}: {e}")

    @app.route("/api/detect", methods=["POST"])
    def detect():
        request_start = time.time()
        p1 = None
        p2 = None

        Log.info("\n" + "#"*70)
        Log.info("#"*70)
        Log.info("###  🚀 BẮT ĐẦU REQUEST MỚI")
        Log.info(f"###  ⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")
        Log.info("#"*70 + "\n")

        try:
            # ==================== BƯỚC 1: VALIDATE ====================
            step_start = time.time()
            Log.info("[API] 📋 Bước 1: Validate request...")
            
            # Validate params
            doc_type, error_resp, status_code = validate_request_params(request)
            if error_resp:
                Log.error(f"[API] ❌ Validation Failed: {error_resp.json}")
                return error_resp, status_code

            # Initialize variables
            raw_front = []
            raw_back = []
            ocr_front_time = 0.0
            ocr_back_time = 0.0

            # 🆕 CHECK: RAW TEXT INPUT (Bypass OCR)
            raw_text_input = request.form.get("raw_text")

            if raw_text_input:
                Log.info("[API] 📝 Nhận diện 'raw_text' -> Bỏ qua OCR, xử lý trực tiếp.")
                # Tách chuỗi thành list các dòng
                raw_front = [line.strip() for line in raw_text_input.strip().split('\n') if line.strip()]
                Log.info(f"[API]    📝 Input lines: {len(raw_front)}")
            
            else:
                # 📷 FILE UPLOAD FLOW
                if "first_image" not in request.files and "second_image" not in request.files:
                    return jsonify({"statusCode": 400, "message": "Cần ít nhất 1 file (first_image hoặc second_image) hoặc field 'raw_text'"}), 400

                f1 = request.files.get("first_image")
                f2 = request.files.get("second_image")
                
                Log.info(f"[API] ✅ Validation OK (Type: {doc_type}) - {time.time() - step_start:.2f}s")

                # ==================== BƯỚC 2: LƯU FILE ====================
                step_start = time.time()
                Log.info("[API] 💾 Bước 2: Lưu file...")
                p1, p2 = save_uploaded_files(f1, f2)
                if p1: Log.info(f"[API]    📁 Front: {p1}")
                if p2: Log.info(f"[API]    📁 Back: {p2}")
                Log.info(f"[API] ✅ Lưu file xong - {time.time() - step_start:.2f}s")

                # ==================== BƯỚC 3: OCR HAI MẶT ====================
                Log.info("[API] 🔍 Bước 3: OCR...")

                if p1:
                    t = time.time()
                    raw_front, _ = ocr_extract(p1)
                    ocr_front_time = time.time() - t
                    Log.info(f"[API]    ⏳ OCR front: {ocr_front_time:.2f}s")

                if p2:
                    t = time.time()
                    raw_back, _ = ocr_extract(p2)
                    ocr_back_time = time.time() - t
                    Log.info(f"[API]    ⏳ OCR back : {ocr_back_time:.2f}s")

            Log.info("[API] ✅ OCR xong")

            Log.info("-" * 30)
            Log.info(f"[API] 📝 RAW OCR FRONT ({len(raw_front)} lines):")
            for line in raw_front:
                Log.info(f"   > {line}")
            
            Log.info("-" * 30)
            Log.info(f"[API] 📝 RAW OCR BACK ({len(raw_back)} lines):")
            for line in raw_back:
                Log.info(f"   > {line}")
            Log.info("-" * 30)

            timer_info = {
                "start": request_start,
                "ocr_front": ocr_front_time,
                "ocr_back": ocr_back_time
            }

            # Check rate limiter first
            should_skip_gemini = False
            if gemini_limiter.is_blocked():
                 Log.warning(f"[API] ⚠️ Gemini Limit/Fallback active. Remaining: {gemini_limiter.get_remaining_time():.0f}s. Fallback traditional.")
                 should_skip_gemini = True

            if not should_skip_gemini:
                 # Pass doc_type to gemini
                 response = process_with_gemini(raw_front, raw_back, timer_info, doc_type=doc_type)
                 if response:
                     return response
            
            # If doc_type is NOT idCard, traditional might not work as it is tailored for idCard.
            if doc_type != "idCard":
                 Log.warning(f"[API] ⚠️ Traditional pipeline is designed for idCard (CCCD). It may fail for {doc_type}.")
            
            

            return process_traditional(
                raw_front, raw_back, 
                timer_info, 
                doc_type=doc_type,
            )

        except Exception as e:
            Log.error("\n" + "!"*70)
            Log.error(f"[API] ❌ LỖI: {str(e)}")
            Log.error("!"*70 + "\n")

            return jsonify({
                "statusCode": 500,
                "message": "Lỗi server",
                "error": str(e)
            }), 500
        
        finally:
            # Cleanup uploaded files
            if p1 and os.path.exists(p1):
                try:
                    os.remove(p1)
                    Log.info(f"[CLEANUP] 🗑️ Deleted {p1}")
                except Exception as e:
                    Log.error(f"[CLEANUP] ⚠️ Failed to delete {p1}: {e}")
            
            if p2 and os.path.exists(p2):
                try:
                    os.remove(p2)
                    Log.info(f"[CLEANUP] 🗑️ Deleted {p2}")
                except Exception as e:
                    Log.error(f"[CLEANUP] ⚠️ Failed to delete {p2}: {e}")

