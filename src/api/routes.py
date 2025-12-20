"""
API Routes
Định nghĩa các API endpoints cho CCCD OCR
"""
import time
import os
from datetime import datetime
from flask import request, jsonify, send_from_directory
from src.utils.auth_middleware import require_auth
from src.utils.file_utils import allowed_file, save_uploaded_files
from src.utils.ocr_utils import ocr_extract
from src.api.processors.ai_processor import process_with_grok, process_with_gemini
from src.api.processors.traditional_processor import process_traditional
from src.utils.logger import Log



from src.utils.grok_limiter import grok_limiter

from src.extractors.gemini_extractor import gemini_extractor

from src.utils.smart_config import get_smart_config
from src.utils.post_cleaner import PostCleaner
from src.utils.gemini_limiter import gemini_limiter
from src.utils.smart_spatial_extractor import SmartSpatialExtractor
from src.utils.logger import Log
from src.services.log_service import log_service



ALLOWED_DOC_TYPES = {'idCard', 'driverLicense', 'invoice', 'document', 'vehicleDocuments'}
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB limit





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

    @app.route('/uploads/<path:filename>')
    def serve_uploaded_file(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    @app.route("/api/stats", methods=["GET"])
    @require_auth
    def get_user_stats():
        """
        Get extraction statistics for the authenticated user
        Returns total extractions and breakdown by document type
        """
        try:
            from flask import g
            from src.repositories.users_repository import users_repo
            
            user_id = getattr(g, 'user_id', None)
            if not user_id:
                return jsonify({"statusCode": 401, "message": "User not authenticated"}), 401
            
            # Fetch user from database
            user_data = users_repo.find_by_id(user_id)
            if not user_data:
                return jsonify({"statusCode": 404, "message": "User not found"}), 404
            
            # Extract stats
            stats = user_data.get("stats", {})
            total_extractions = stats.get("total_extractions", 0)
            last_extraction_at = stats.get("last_extraction_at")
            doc_type_stats = stats.get("doc_type_stats", {})
            # Ensure standard types are present in breakdown
            for dt in ["idCard", "driverLicense", "invoice", "document", "vehicleDocuments"]:
                if dt not in doc_type_stats:
                    doc_type_stats[dt] = 0
            
            # Get daily count
            from src.repositories.extraction_logs_repository import extraction_logs_repo
            today_extractions = extraction_logs_repo.count_today_by_user(user_id)

            return jsonify({
                "statusCode": 200,
                "message": "Success",
                "data": {
                    "total_extractions": total_extractions,
                    "today_extractions": today_extractions,
                    "last_extraction_at": last_extraction_at.isoformat() if last_extraction_at else None,
                    "breakdown": doc_type_stats
                }
            }), 200
            
        except Exception as e:
            Log.error(f"[API] Error fetching user stats: {e}")
            return jsonify({
                "statusCode": 500,
                "message": "Internal server error",
                "error": str(e)
            }), 500

    @app.route("/api/traditional", methods=["POST"])
    @require_auth
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
                # Check if 'files' is present and not empty
                has_files_list = 'files' in request.files and len(request.files.getlist('files')) > 0
                
                if has_files_list:
                    # 🧾 MULTI-FILE FLOW
                    files = request.files.getlist('files')
                    
                    if len(files) > 5:
                         return jsonify({"statusCode": 400, "message": "Tối đa 5 ảnh"}), 400
                    
                    Log.info(f"[API-TRAD] 📦 Multi-file Mode: Received {len(files)} files")
                    
                    # Save files
                    from src.utils.file_utils import save_uploaded_file_list
                    saved_paths = save_uploaded_file_list(files)
                    
                    cleanup_extra = [] 
                    
                    if len(saved_paths) > 0: p1 = saved_paths[0]
                    if len(saved_paths) > 1: p2 = saved_paths[1]
                    if len(saved_paths) > 2: cleanup_extra = saved_paths[2:]
                    
                    # OCR each file
                    total_ocr_time = 0
                    for path in saved_paths:
                        t = time.time()
                        ocr_result, _ = ocr_extract(path)
                        # Add separator for context if multiple files
                        if len(saved_paths) > 1:
                            raw_front.extend([f"--- PAGE/IMAGE START: {os.path.basename(path)} ---"])
                        
                        raw_front.extend(ocr_result)
                        total_ocr_time += (time.time() - t)
                    
                    ocr_front_time = total_ocr_time
                    Log.info(f"[API-TRAD]    ⏳ Total OCR time: {ocr_front_time:.2f}s")
                    
                    # Cleanup extra files immediately
                    for extra_path in cleanup_extra:
                        try:
                            if os.path.exists(extra_path):
                                os.remove(extra_path)
                                Log.info(f"[CLEANUP] 🗑️ Deleted extra file {extra_path}")
                        except: pass

                else:
                    # 📷 SINGLE/DOUBLE FILE UPLOAD FLOW (LEGACY/STD)
                    if "first_image" not in request.files and "second_image" not in request.files:
                        return jsonify({"statusCode": 400, "message": "Cần ít nhất 1 file (files, first_image hoặc second_image) hoặc field 'raw_text'"}), 400

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
            # Get user_id from Flask g context (set by @require_auth)
            from flask import g
            return process_traditional(
                raw_front, raw_back, 
                timer_info, 
                doc_type=doc_type,
                user_id=user_id,
                file_paths=[p for p in [p1, p2] if p] if (p1 or p2) else []
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
            

    @app.route("/api/grok", methods=["POST"])
    @require_auth
    def detect_grok():
        request_start = time.time()
        p1 = None
        p2 = None
        all_temp_files = []

        Log.info("\n" + "#"*70)
        Log.info("###  🚀 GROK TEST REQUEST")
        Log.info(f"###  ⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")
        Log.info("#"*70 + "\n")

        try:
            # ==================== BƯỚC 1: VALIDATE ====================
            step_start = time.time()
            Log.info("[API-GROK] 📋 Bước 1: Validate request...")
            
            # Validate params
            doc_type, error_resp, status_code = validate_request_params(request)
            if error_resp:
                Log.error(f"[API-GROK] ❌ Validation Failed: {error_resp.json}")
                return error_resp, status_code

            # Initialize variables
            raw_front = []
            raw_back = []
            ocr_front_time = 0.0
            ocr_back_time = 0.0

            # 🆕 CHECK: RAW TEXT INPUT (Bypass OCR)
            raw_text_input = request.form.get("raw_text")

            if raw_text_input:
                Log.info("[API-GROK] 📝 Nhận diện 'raw_text' -> Bỏ qua OCR, xử lý trực tiếp.")
                raw_front = [line.strip() for line in raw_text_input.strip().split('\\n') if line.strip()]
                Log.info(f"[API-GROK]    📝 Input lines: {len(raw_front)}")
            
            else:
                # Check if 'files' is present and not empty
                has_files_list = 'files' in request.files and len(request.files.getlist('files')) > 0
                
                if has_files_list:
                    # 🧾 MULTI-FILE FLOW
                    files = request.files.getlist('files')
                    
                    if len(files) > 5:
                         return jsonify({"statusCode": 400, "message": "Tối đa 5 ảnh"}), 400
                    
                    Log.info(f"[API-GROK] 📦 Multi-file Mode: Received {len(files)} files")
                    
                    # Save files
                    from src.utils.file_utils import save_uploaded_file_list
                    saved_paths = save_uploaded_file_list(files)
                    all_temp_files.extend(saved_paths)
                    
                    if len(saved_paths) > 0: p1 = saved_paths[0]
                    if len(saved_paths) > 1: p2 = saved_paths[1]
                    
                    # OCR each file
                    total_ocr_time = 0
                    for path in saved_paths:
                        t = time.time()
                        ocr_result, _ = ocr_extract(path)
                        if len(saved_paths) > 1:
                            raw_front.extend([f"--- PAGE/IMAGE START: {os.path.basename(path)} ---"])
                        raw_front.extend(ocr_result)
                        total_ocr_time += (time.time() - t)
                    
                    ocr_front_time = total_ocr_time
                    Log.info(f"[API-GROK]    ⏳ Total OCR time: {ocr_front_time:.2f}s")

                else:
                    # 📷 SINGLE/DOUBLE FILE UPLOAD FLOW
                    if "first_image" not in request.files and "second_image" not in request.files:
                        return jsonify({"statusCode": 400, "message": "Cần ít nhất 1 file (files, first_image hoặc second_image) hoặc field 'raw_text'"}), 400

                    f1 = request.files.get("first_image")
                    f2 = request.files.get("second_image")
                    
                    Log.info(f"[API-GROK] ✅ Validation OK (Type: {doc_type}) - {time.time() - step_start:.2f}s")

                    # ==================== BƯỚC 2: LƯU FILE ====================
                    step_start = time.time()
                    Log.info("[API-GROK] 💾 Bước 2: Lưu file...")
                    p1, p2 = save_uploaded_files(f1, f2)
                    if p1: all_temp_files.append(p1)
                    if p2: all_temp_files.append(p2)

                    if p1: Log.info(f"[API-GROK]    📁 Front: {p1}")
                    if p2: Log.info(f"[API-GROK]    📁 Back: {p2}")

                    # ==================== BƯỚC 3: OCR HAI MẶT ====================
                    Log.info("[API-GROK] 🔍 Bước 3: OCR...")

                    if p1:
                        t = time.time()
                        raw_front, _ = ocr_extract(p1)
                        ocr_front_time = time.time() - t
                        Log.info(f"[API-GROK]    ⏳ OCR front: {ocr_front_time:.2f}s")

                    if p2:
                        t = time.time()
                        raw_back, _ = ocr_extract(p2)
                        ocr_back_time = time.time() - t
                        Log.info(f"[API-GROK]    ⏳ OCR back : {ocr_back_time:.2f}s")

            Log.info("[API-GROK] ✅ OCR xong")
            
            timer_info = {
                "start": request_start,
                "ocr_front": ocr_front_time,
                "ocr_back": ocr_back_time
            }

            # FORCE GROK FLOW
            from flask import g
            user_id = getattr(g, 'user_id', None)
            
            try:
                response = process_with_grok(raw_front, raw_back, timer_info, doc_type=doc_type, user_id=user_id, file_paths=all_temp_files)
                if response: return response
                # If None was returned
                return jsonify({"statusCode": 500, "message": "Grok processing returned no data"}), 500
            except Exception as e:
                # If process_with_grok raises exception, it comes here
                raise e

        except Exception as e:
            Log.error("\n" + "!"*70)
            Log.error(f"[API-GROK] ❌ LỖI: {str(e)}")
            Log.error("!"*70 + "\n")

            return jsonify({
                "statusCode": 500,
                "message": "Lỗi server",
                "error": str(e)
            }), 500
        
        finally:
            # Cleanup uploaded files
            for f_path in all_temp_files:
                if f_path and os.path.exists(f_path):
                    try:
                        os.remove(f_path)
                    except: pass

    @app.route("/api/detect", methods=["POST"])
    @require_auth
    def detect():
        request_start = time.time()
        p1 = None
        p2 = None
        all_temp_files = []

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
                # Check if 'files' is present and not empty
                has_files_list = 'files' in request.files and len(request.files.getlist('files')) > 0
                
                if has_files_list:
                    # 🧾 MULTI-FILE FLOW (For Invoice or any Doc Type)
                    files = request.files.getlist('files')
                    
                    if len(files) > 5:
                         return jsonify({"statusCode": 400, "message": "Tối đa 5 ảnh"}), 400
                    
                    Log.info(f"[API] 📦 Multi-file Mode: Received {len(files)} files")
                    
                    # Save files
                    from src.utils.file_utils import save_uploaded_file_list
                    saved_paths = save_uploaded_file_list(files)
                    all_temp_files.extend(saved_paths)
                    
                    # Assign to p1/p2 for cleanup compatibility (first 2 files)
                    if len(saved_paths) > 0: p1 = saved_paths[0]
                    if len(saved_paths) > 1: p2 = saved_paths[1]

                    # Process loop for OCR (simple sequential for now)
                    # Note: Current detect logic expects raw_front/raw_back specifically.
                    # Adapting logic: Concatenate all OCR results into 'raw_front' for now?
                    # Or just process first 2 as front/back.
                    # Assuming Invoice logic uses only p1 (front).
                    # For compatibility, we'll just populate raw_front with all text from all pages.
                    
                    if doc_type == 'invoice':
                        # Invoice Loop
                        for idx, path in enumerate(saved_paths):
                            t = time.time()
                            data, _ = ocr_extract(path)
                            ocr_front_time += (time.time() - t)
                            # Extend raw_front with data (list ofdicts)
                            if data: raw_front.extend(data)
                    else:
                        # Legacy Doc Type Loop (CCCD/License) - Expects 2 sides max usually
                        if p1:
                             t = time.time()
                             raw_front, _ = ocr_extract(p1)
                             ocr_front_time += (time.time() - t)
                        if p2:
                             t = time.time()
                             raw_back, _ = ocr_extract(p2)
                             ocr_back_time += (time.time() - t)

                elif doc_type == 'invoice':
                     # Invoice requested but no files? Maybe used first_image?
                     # Allow fallthrough to legacy check
                     pass

                if not has_files_list:
                    # 📷 SINGLE/DOUBLE FILE UPLOAD FLOW (LEGACY/STD)
                    if "first_image" not in request.files and "second_image" not in request.files:
                        return jsonify({"statusCode": 400, "message": "Cần ít nhất 1 file (files, first_image hoặc second_image) hoặc field 'raw_text'"}), 400

                    f1 = request.files.get("first_image")
                    f2 = request.files.get("second_image")
                    
                    Log.info(f"[API] ✅ Validation OK (Type: {doc_type}) - {time.time() - step_start:.2f}s")

                    # ==================== BƯỚC 2: LƯU FILE ====================
                    step_start = time.time()
                    Log.info("[API] 💾 Bước 2: Lưu file...")
                    p1, p2 = save_uploaded_files(f1, f2)
                    if p1: all_temp_files.append(p1)
                    if p2: all_temp_files.append(p2)
                    
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
                txt = line.get('text', '') if isinstance(line, dict) else line
                Log.info(f"   > {txt}")
            
            Log.info("-" * 30)
            Log.info(f"[API] 📝 RAW OCR BACK ({len(raw_back)} lines):")
            for line in raw_back:
                txt = line.get('text', '') if isinstance(line, dict) else line
                Log.info(f"   > {txt}")
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

            # Get user_id from Flask g context (set by @require_auth)
            from flask import g
            user_id = getattr(g, 'user_id', None)
            
            # Check provider param
            provider = request.form.get("provider", "auto")
            
            # --- 1. FORCE PROVIDERS ---
            if provider == 'grok':
                try:
                    response = process_with_grok(raw_front, raw_back, timer_info, doc_type=doc_type, user_id=user_id, file_paths=all_temp_files)
                    if response: return response
                except Exception as e:
                    Log.warning(f"[API] ⚠️ Grok failed: {e}. Fallback to traditional.")

            elif provider == 'gemini':
                # Explicit Gemini Request
                if not should_skip_gemini:
                    try:
                        response = process_with_gemini(raw_front, raw_back, timer_info, doc_type=doc_type, user_id=user_id, file_paths=all_temp_files)
                        if response: return response
                    except Exception as e:
                        Log.warning(f"[API] ⚠️ Gemini failed: {e}. Fallback to traditional.")
                else:
                     Log.warning(f"[API] ⚠️ Gemini skipped (Rate Limit). Fallback to traditional.")

            # --- 2. AUTO CHAIN: GROK (Priority) -> GEMINI (Fallback 1) -> TRADITIONAL (Fallback 2) ---
            else:
                should_skip_grok = False
                if grok_limiter.is_blocked():
                    Log.warning(f"[API] ⚠️ Grok Limit active. Remaining: {grok_limiter.get_remaining_time():.0f}s. Skipping to Gemini.")
                    should_skip_grok = True

                # A. Try Grok
                if not should_skip_grok:
                    try:
                        response = process_with_grok(raw_front, raw_back, timer_info, doc_type=doc_type, user_id=user_id, file_paths=all_temp_files)
                        if response: return response
                        # If response is None, it means fallback initiated by grok logic (429/503)
                    except Exception as grok_e:
                        Log.warning(f"[API] ⚠️ Grok failed ({grok_e}). Trying Gemini...")

                # B. Try Gemini (If Grok failed)
                if not should_skip_gemini:
                    try:
                         response = process_with_gemini(raw_front, raw_back, timer_info, doc_type=doc_type, user_id=user_id, file_paths=all_temp_files)
                         if response: return response
                    except Exception as gemini_e:
                         Log.warning(f"[API] ⚠️ Gemini failed cleanly ({gemini_e}). Fallback to traditional.")
                else:
                    Log.warning(f"[API] ⚠️ Gemini skipped (Rate Limit). Fallback to traditional.")
            
            
            
            return process_traditional(
                raw_front, raw_back, 
                timer_info, 
                doc_type=doc_type,
                user_id=user_id,
                file_paths=all_temp_files
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
            # Cleanup all temporary files
            for f_path in all_temp_files:
                if f_path and os.path.exists(f_path):
                    try:
                        os.remove(f_path)
                        Log.info(f"[CLEANUP] 🗑️ Deleted {f_path}")
                    except Exception as e:
                        Log.error(f"[CLEANUP] ⚠️ Failed to delete {f_path}: {e}")

