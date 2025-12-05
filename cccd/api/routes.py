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


def register_routes(app):
    """
    Đăng ký các routes cho Flask app
    
    Args:
        app: Flask application instance
    """
    
    @app.route("/api/detect", methods=["POST"])
    def detect():
        """
        API endpoint để detect và trích xuất thông tin CCCD
        
        Request:
            - front_image: File ảnh mặt trước
            - back_image: File ảnh mặt sau
            
        Response:
            - statusCode: Mã trạng thái
            - message: Thông điệp
            - data: Thông tin đã trích xuất
            - debug: Thông tin debug (thời gian xử lý)
        """
        request_start = time.time()
        print(f"\n\n{'#'*70}")
        print(f"{'#'*70}")
        print(f"###  🚀 BẮT ĐẦU REQUEST MỚI")
        print(f"###  ⏰ Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")
        print(f"{'#'*70}")
        print(f"{'#'*70}\n")
        
        try:
            # ==================== BƯỚC 1: VALIDATE ====================
            step_start = time.time()
            print(f"[API] 📋 Bước 1: Validate request...")
            
            if "front_image" not in request.files or "back_image" not in request.files:
                print(f"[API] ❌ Thiếu file ảnh")
                return jsonify({"statusCode": 400, "message": "Thiếu file"}), 400

            f1 = request.files["front_image"]
            f2 = request.files["back_image"]

            if not allowed_file(f1.filename) or not allowed_file(f2.filename):
                print(f"[API] ❌ Sai định dạng file")
                return jsonify({"statusCode": 400, "message": "Sai định dạng file"}), 400

            print(f"[API] ✅ Validation OK - {time.time() - step_start:.2f}s\n")

            # ==================== BƯỚC 2: LƯU FILE ====================
            step_start = time.time()
            print(f"[API] 💾 Bước 2: Lưu file...")
            p1, p2 = save_uploaded_files(f1, f2)
            print(f"[API] ✅ Đã lưu file - {time.time() - step_start:.2f}s")
            print(f"[API]    📁 Front: {p1}")
            print(f"[API]    📁 Back: {p2}\n")

            # ==================== BƯỚC 3: OCR MẶT TRƯỚC ====================
            step_start = time.time()
            print(f"[API] 🔍 Bước 3: OCR mặt trước...")
            raw_front, _ = ocr_extract(p1)
            ocr_front_time = time.time() - step_start
            print(f"[API] ✅ OCR mặt trước xong - {ocr_front_time:.2f}s\n")

            # ==================== BƯỚC 4: OCR MẶT SAU ====================
            step_start = time.time()
            print(f"[API] 🔍 Bước 4: OCR mặt sau...")
            raw_back, _ = ocr_extract(p2)
            ocr_back_time = time.time() - step_start
            print(f"[API] ✅ OCR mặt sau xong - {ocr_back_time:.2f}s\n")

            # ==================== BƯỚC 5: LỌC TEXT MẶT TRƯỚC ====================
            step_start = time.time()
            print(f"[API] 🗑️  Bước 5: Lọc text mặt trước...")
            filtered_front = filter_useless_lines(raw_front)
            filter_front_time = time.time() - step_start
            print(f"[API] ✅ Lọc mặt trước xong - {filter_front_time:.2f}s\n")

            # ==================== BƯỚC 6: LỌC TEXT MẶT SAU ====================
            step_start = time.time()
            print(f"[API] 🗑️  Bước 6: Lọc text mặt sau...")
            filtered_back = filter_useless_lines(raw_back)
            filter_back_time = time.time() - step_start
            print(f"[API] ✅ Lọc mặt sau xong - {filter_back_time:.2f}s\n")

            # ==================== BƯỚC 7: CLEAN MẶT TRƯỚC ====================
            step_start = time.time()
            print(f"[API] 🧹 Bước 7: Làm sạch mặt trước (có chọn lọc)...")
            clean_front = selective_clean_text_front(filtered_front)
            clean_front_time = time.time() - step_start
            print(f"[API] ✅ Làm sạch mặt trước xong - {clean_front_time:.2f}s\n")

            # ==================== BƯỚC 8: CLEAN MẶT SAU ====================
            step_start = time.time()
            print(f"[API] 🎯 Bước 8: Làm sạch có chọn lọc mặt sau (chỉ ngày tháng)...")
            clean_back = selective_clean_text_back(filtered_back)
            clean_back_time = time.time() - step_start
            print(f"[API] ✅ Làm sạch mặt sau xong - {clean_back_time:.2f}s\n")

            # ==================== BƯỚC 9: TRÍCH XUẤT THÔNG TIN ====================
            step_start = time.time()
            print(f"[API] 📊 Bước 9: Trích xuất thông tin...")
            info_front = extract_front(clean_front)
            info_back = extract_back(clean_back)
            extract_time = time.time() - step_start
            print(f"[API] ✅ Trích xuất xong - {extract_time:.2f}s\n")

            # ==================== TỔNG KẾT ====================
            total_time = time.time() - request_start

            print(f"\n{'='*70}")
            print(f"📊 TỔNG KẾT THỜI GIAN")
            print(f"{'='*70}")
            print(f"  OCR mặt trước:        {ocr_front_time:>8.2f}s")
            print(f"  OCR mặt sau:          {ocr_back_time:>8.2f}s")
            print(f"  Lọc mặt trước:        {filter_front_time:>8.2f}s")
            print(f"  Lọc mặt sau:          {filter_back_time:>8.2f}s")
            print(f"  Clean mặt trước:      {clean_front_time:>8.2f}s  🧹 (CÓ CHỌN LỌC)")
            print(f"  Clean mặt sau:        {clean_back_time:>8.2f}s  🎯 (CHỈ NGÀY)")
            print(f"  Trích xuất:           {extract_time:>8.2f}s")
            print(f"  {'─'*70}")
            print(f"  TỔNG CỘNG:            {total_time:>8.2f}s")
            print(f"{'='*70}\n")

            print(f"[API] 🎉 Trả về kết quả cho client\n")

            return jsonify({
                "statusCode": 200,
                "message": "Success",
                "data": {**info_front, **info_back},
                "debug": {
                    "total_time": f"{total_time:.2f}s",
                    "ocr_time": f"{ocr_front_time + ocr_back_time:.2f}s",
                    "filter_time": f"{filter_front_time + filter_back_time:.2f}s",
                    "clean_time": f"{clean_front_time + clean_back_time:.2f}s"
                }
            })

        except Exception as e:
            error_time = time.time() - request_start
            print(f"\n{'!'*70}")
            print(f"[API] ❌ LỖI XẢY RA")
            print(f"[API] ⏱️  Thời gian trước khi lỗi: {error_time:.2f}s")
            print(f"[API] 💥 Chi tiết lỗi: {str(e)}")
            print(f"{'!'*70}\n")
            
            return jsonify({
                "statusCode": 500,
                "message": "Lỗi server",
                "error": str(e)
            }), 500
