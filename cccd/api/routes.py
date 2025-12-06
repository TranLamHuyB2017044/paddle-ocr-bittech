"""
API Routes
Định nghĩa các API endpoints cho CCCD OCR
"""
import time
from datetime import datetime
from flask import request, jsonify

from cccd.utils.file_utils import allowed_file, save_uploaded_files
from cccd.utils.ocr_utils import ocr_extract, filter_useless_lines
from cccd.utils.text_cleaner import selective_clean_text_front, selective_clean_text_back
from cccd.extractors.front_extractor import extract_front
from cccd.extractors.back_extractor import extract_back
from cccd.extractors.gemini_extractor import gemini_extractor
from cccd.utils.gemini_limiter import gemini_limiter



def process_with_gemini(raw_front, raw_back, timer_info):
    request_start = timer_info["start"]
    ocr_front_time = timer_info["ocr_front"]
    ocr_back_time = timer_info["ocr_back"]
    
    print("[API] 🤖 Dùng Gemini → bỏ qua toàn bộ bước lọc/clean/regex")
    try:
        raw_text = raw_front + raw_back
        extraction_result = gemini_extractor.extract(raw_text)
        
        info = extraction_result.get("data", {})
        metadata = extraction_result.get("metadata", {})

        total_time = time.time() - request_start

        print("[API] 🎉 Trả về kết quả Gemini\n")
        return jsonify({
            "statusCode": 200,
            "message": "Success (Gemini)",
            "data": info,
            "debug": {
                "total_time": f"{total_time:.2f}s",
                "ocr_time": f"{ocr_front_time + ocr_back_time:.2f}s",
                "gemini": True,
                "gemini_metadata": metadata
            }
        })
    except Exception as e:
        print(f"[API] ⚠️ API Gemini Error: {e}")
        gemini_limiter.record_error(e)
        
        if gemini_limiter.is_blocked():
             print("[API] 🛑 Fallback to traditional due to RateLimit/Timeout.")
             return None # Signal fallback
        else:
             print("[API] ❌ Critical Error (not rate limit). Returning error to user.")
             raise e

def process_traditional(raw_front, raw_back, timer_info):
    request_start = timer_info["start"]
    ocr_front_time = timer_info["ocr_front"]
    ocr_back_time = timer_info["ocr_back"]

    print("[API] 🧹 Dùng pipeline truyền thống (filter + clean + regex)\n")

    # ------------------ BƯỚC 5: FILTER ----------------------
    step_start = time.time()
    filtered_front = filter_useless_lines(raw_front)
    filtered_back = filter_useless_lines(raw_back)
    filter_time = time.time() - step_start
    print(f"[API]    🗑️ Filter xong - {filter_time:.2f}s\n")

    # ------------------ BƯỚC 7: CLEAN ----------------------
    step_start = time.time()
    clean_front = selective_clean_text_front(filtered_front)
    clean_back = selective_clean_text_back(filtered_back)
    clean_time = time.time() - step_start
    print(f"[API]    🧹 Clean xong - {clean_time:.2f}s\n")

    # ------------------ BƯỚC 9: EXTRACT ----------------------
    step_start = time.time()
    info_front = extract_front(clean_front)
    info_back = extract_back(clean_back)
    extract_time = time.time() - step_start
    print(f"[API]    📊 Extract xong - {extract_time:.2f}s\n")

    # ------------------ TỔNG KẾT ----------------------
    total_time = time.time() - request_start

    print("[API] 🎉 Trả về kết quả kiểu truyền thống\n")
    return jsonify({
        "statusCode": 200,
        "message": "Success",
        "data": {**info_front, **info_back},
        "debug": {
            "total_time": f"{total_time:.2f}s",
            "ocr_time": f"{ocr_front_time + ocr_back_time:.2f}s",
            "filter_time": f"{filter_time:.2f}s",
            "clean_time": f"{clean_time:.2f}s",
            "extract_time": f"{extract_time:.2f}s",
            "gemini": False
        }
    })

def register_routes(app):
    """
    Đăng ký các routes cho Flask app
    
    Args:
        app: Flask application instance
    """
    
    @app.route("/api/detect", methods=["POST"])
    def detect():
        request_start = time.time()

        print("\n\n" + "#"*70)
        print("#"*70)
        print("###  🚀 BẮT ĐẦU REQUEST MỚI")
        print(f"###  ⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")
        print("#"*70 + "\n")

        try:
            # ==================== BƯỚC 1: VALIDATE ====================
            step_start = time.time()
            print("[API] 📋 Bước 1: Validate request...")

            if "front_image" not in request.files or "back_image" not in request.files:
                return jsonify({"statusCode": 400, "message": "Thiếu file"}), 400

            f1 = request.files["front_image"]
            f2 = request.files["back_image"]
            
            print(f"[API] ✅ Validation OK - {time.time() - step_start:.2f}s\n")

            # ==================== BƯỚC 2: LƯU FILE ====================
            step_start = time.time()
            print("[API] 💾 Bước 2: Lưu file...")
            p1, p2 = save_uploaded_files(f1, f2)
            print(f"[API]    📁 Front: {p1}")
            print(f"[API]    📁 Back: {p2}")
            print(f"[API] ✅ Lưu file xong - {time.time() - step_start:.2f}s\n")

            # ==================== BƯỚC 3: OCR HAI MẶT ====================
            print("[API] 🔍 Bước 3: OCR hai mặt...")

            t = time.time()
            raw_front, _ = ocr_extract(p1)
            ocr_front_time = time.time() - t

            t = time.time()
            raw_back, _ = ocr_extract(p2)
            ocr_back_time = time.time() - t

            print(f"[API]    ⏳ OCR front: {ocr_front_time:.2f}s")
            print(f"[API]    ⏳ OCR back : {ocr_back_time:.2f}s")
            print("[API] ✅ OCR xong\n")

            timer_info = {
                "start": request_start,
                "ocr_front": ocr_front_time,
                "ocr_back": ocr_back_time
            }

            # Check rate limiter first
            should_skip_gemini = False
            if gemini_limiter.is_blocked():
                 print(f"[API] ⚠️ Gemini Limit/Fallback active. Remaining: {gemini_limiter.get_remaining_time():.0f}s. Fallback traditional.")
                 should_skip_gemini = True

            if not should_skip_gemini:
                 response = process_with_gemini(raw_front, raw_back, timer_info)
                 if response:
                     return response
            
            return process_traditional(raw_front, raw_back, timer_info)

        except Exception as e:
            print("\n" + "!"*70)
            print("[API] ❌ LỖI:", str(e))
            print("!"*70 + "\n")

            return jsonify({
                "statusCode": 500,
                "message": "Lỗi server",
                "error": str(e)
            }), 500

