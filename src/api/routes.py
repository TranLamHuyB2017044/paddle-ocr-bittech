"""
API Routes
Định nghĩa các API endpoints cho CCCD OCR (Phiên bản Bất đồng bộ)
"""
import os
from flask import request, jsonify, send_from_directory, g
import requests
from werkzeug.utils import secure_filename
from datetime import datetime
import uuid
from src.utils.auth_middleware import require_auth
from src.utils.file_utils import save_uploaded_files
from src.utils.redis_client import rag_queue
from src.tasks.document_tasks import process_detection_task
from src.repositories.documents_repository import documents_repo
from src.utils.logger import Log
from src.config import MAX_OCR_FILE_SIZE, DocStatus, PLANS_CONFIG, UPLOAD_FOLDER
from src.services.subscription_service import subscription_service
from src.repositories.accounts_repository import accounts_repo
from src.api.processors.traditional_processor import process_traditional

ALLOWED_DOC_TYPES = {'idCard', 'driverLicense', 'invoice', 'document', 'vehicleDocuments', 'menu'}

def validate_request_params(req):
    """
    Validate request parameters and files
    """
    if req.content_length and req.content_length > MAX_OCR_FILE_SIZE:
        return None, jsonify({"statusCode": 413, "message": f"File quá lớn. Giới hạn {MAX_OCR_FILE_SIZE/1024/1024}MB"}), 413

    doc_type = req.form.get("type")
    
    if not doc_type:
        return None, jsonify({"statusCode": 400, "message": "Missing 'type' parameter. Required one of: idCard, driverLicense, invoice, document"}), 400
 
    if doc_type not in ALLOWED_DOC_TYPES:
         return None, jsonify({"statusCode": 400, "message": f"Loại giấy tờ không hợp lệ. Cho phép: {ALLOWED_DOC_TYPES}"}), 400

    return doc_type, None, None

def register_routes(app):
    """
    Đăng ký các routes cho Flask app
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
        try:
            from src.repositories.users_repository import users_repo
            user_id = getattr(g, 'user_id', None)
            if not user_id:
                return jsonify({"statusCode": 401, "message": "User not authenticated"}), 401
            
            user_data = users_repo.find_by_id(user_id)
            if not user_data:
                return jsonify({"statusCode": 404, "message": "User not found"}), 404
            
            stats = user_data.get("stats", {})
            total_extractions = stats.get("total_extractions", 0)
            last_extraction_at = stats.get("last_extraction_at")
            doc_type_stats = stats.get("doc_type_stats", {})
            
            breakdown = {
                "idCard": doc_type_stats.get("idCard", 0),
                "driverLicense": doc_type_stats.get("driverLicense", 0),
                "invoice": doc_type_stats.get("invoice", 0),
                "document": doc_type_stats.get("document", 0),
                "vehicleDocuments": doc_type_stats.get("vehicleDocuments", 0) + doc_type_stats.get("vehicle_documents", 0),
                "vehicle": doc_type_stats.get("vehicleDocuments", 0) + doc_type_stats.get("vehicle_documents", 0)
            }
            
            from src.repositories.extraction_logs_repository import extraction_logs_repo
            today_extractions = extraction_logs_repo.count_today_by_user(user_id)

            managed_members_count = 0
            query_user_ids = [user_data.get("_id")]
            
            role = user_data.get("role", 2)
            account_id = user_data.get("account_id")
            
            if role == 0:
                # Admin: thấy toàn bộ hệ thống
                query_user_ids = None
                managed_members_count = users_repo.collection.count_documents({})
            elif role == 1 and account_id:
                # Manager: thấy tất cả thành viên trong cùng account
                team_members = list(users_repo.collection.find({"account_id": account_id}, {"_id": 1, "role": 1}))
                managed_members_count = sum(1 for m in team_members if m.get("role") == 2)
                query_user_ids = [m["_id"] for m in team_members]

            recent_extractions = extraction_logs_repo.get_recent_extractions(query_user_ids, limit=5)

            return jsonify({
                "statusCode": 200,
                "message": "Success",
                "data": {
                    "total_extractions": total_extractions,
                    "today_extractions": today_extractions,
                    "last_extraction_at": last_extraction_at.isoformat() if last_extraction_at else None,
                    "breakdown": breakdown,
                    "doc_type_stats": breakdown,
                    "recent_extractions": recent_extractions,
                    "managed_members": managed_members_count
                }
            }), 200
        except Exception as e:
            Log.error(f"[API] Error fetching user stats: {e}")
            return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500


    @app.route("/api/traditional", methods=["POST"])
    @require_auth
    def detect_traditional():
        import time
        import json
        from src.utils.redis_client import redis_conn, publish_event

        try:
            doc_type, error_resp, status_code = validate_request_params(request)
            if error_resp: return error_resp, status_code

            all_temp_files = []
            files = request.files.getlist('files')
            if files:
                from src.utils.file_utils import save_uploaded_file_list
                all_temp_files = save_uploaded_file_list(files)
            else:
                f1 = request.files.get("first_image")
                f2 = request.files.get("second_image")
                p1, p2 = save_uploaded_files(f1, f2)
                if p1: all_temp_files.append(p1)
                if p2: all_temp_files.append(p2)

            if not all_temp_files:
                return jsonify({"statusCode": 400, "message": "No images provided"}), 400

            user_id = getattr(g, 'user_id', None)
            doc_id = documents_repo.save_document(
                user_id=user_id, doc_type=doc_type,
                filename=os.path.basename(all_temp_files[0]),
                status=DocStatus.UPLOADED
            )

            # Check quota
            is_allowed, msg = subscription_service.check_quota(g.user)
            if not is_allowed:
                return jsonify({"statusCode": 403, "message": msg}), 403

            # ===== 3. Đăng ký lắng nghe TRƯỚC khi gửi task =====
            pubsub = redis_conn.pubsub()
            channel = f"sse_user_{user_id}"
            pubsub.subscribe(channel)

            # Inform SSE about the new task
            publish_event(user_id, "detection_status", {
                "document_id": doc_id,
                "status": DocStatus.UPLOADED,
                "type": doc_type,
                "message": msg
            })

            # Increment usage
            if g.user.get('account_id'):
                accounts_repo.increment_usage(g.user.get('account_id'))

            rag_queue.enqueue(
                process_detection_task,
                args=(doc_id, user_id, doc_type, all_temp_files, "traditional"),
                job_timeout='5m'
            )

            # ===== 4. Lắng nghe Redis & Double Check DB =====
            wait_timeout = 10 # Giảm timeout xuống 10s để tránh chiếm dụng thread quá lâu
            start_wait = time.time()
            final_result = None

            # Kiểm tra nhanh xem Worker đã làm xong chưa (cho trường hợp QR cực nhanh)
            doc_check = documents_repo.find_by_id(doc_id)
            if doc_check and doc_check.get("status") == DocStatus.READY:
                final_result = {
                    "statusCode": 200,
                    "message": "Success (Traditional Fast-Path)",
                    "data": doc_check.get("result"),
                    "debug": doc_check.get("debug")
                }

            if not final_result:
                while time.time() - start_wait < wait_timeout:
                    message = pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0
                    )

                    if message:
                        try:
                            payload = json.loads(message["data"])
                            data = payload.get("data", {})

                            if str(data.get("document_id")) == str(doc_id):
                                status = data.get("status")

                                if status == DocStatus.READY:
                                    final_result = {
                                        "statusCode": 200,
                                        "message": "Success (Traditional Synchronized)",
                                        "data": data.get("result"),
                                        "debug": data.get("debug")
                                    }
                                    break

                                elif status == DocStatus.FAILED:
                                    final_result = {
                                        "statusCode": 500,
                                        "message": f"Processing failed: {data.get('error')}"
                                    }
                                    break
                        except Exception:
                            pass

                    time.sleep(0.1)

            pubsub.unsubscribe(channel)
            pubsub.close()

            if final_result:
                return jsonify(final_result), final_result["statusCode"]

            return jsonify({
                "statusCode": 202,
                "message": "Detection task enqueued (Wait Timeout). Please check status or listen to SSE.",
                "data": {"document_id": doc_id}
            }), 202

        except Exception as e:
            Log.error(f"[API-TRAD] ❌ Error: {e}")
            return jsonify({"statusCode": 500, "message": str(e)}), 500

    @app.route("/api/document/<doc_id>", methods=["GET"])
    @require_auth
    def get_document_status(doc_id):
        """
        Get document status and results
        """
        try:
            doc = documents_repo.find_by_id(doc_id)
            if not doc:
                return jsonify({"statusCode": 404, "message": "Document not found"}), 404
            
            # Authorization check
            if str(doc.get("user_id")) != str(g.user_id):
                return jsonify({"statusCode": 403, "message": "Access denied"}), 403
            
            # Format response
            res = {
                "document_id": str(doc["_id"]),
                "status": doc.get("status"),
                "type": doc.get("document_type"),
                "result": doc.get("result"),
                "error": doc.get("error"),
                "created_at": doc.get("created_at")
            }
            return jsonify({"statusCode": 200, "data": res}), 200
        except Exception as e:
            return jsonify({"statusCode": 500, "message": str(e)}), 500


    @app.route("/api/detect-sync", methods=["POST"])
    @require_auth
    def detect_sync():
        """
        [SYNC-VIA-WORKER]
        Cho phép xử lý với:
        - raw_text
        - files[]
        - first_image (optional)
        - second_image (optional)
        """
        import time
        import json
        import os
        from src.utils.redis_client import redis_conn
        from src.utils.file_utils import save_uploaded_files

        try:
            doc_type, error_resp, status_code = validate_request_params(request)
            if error_resp:
                return error_resp, status_code

            # ===== 1. Thu thập raw_text + files (OPTIONAL) =====
            raw_text = request.form.get("raw_text")

            all_temp_files = []

            # (1) files[]
            files = request.files.getlist("files")
            if files and len(files) > 0:
                from src.utils.file_utils import save_uploaded_file_list
                all_temp_files = save_uploaded_file_list(files)

            # (2) fallback: first_image / second_image
            else:
                f1 = request.files.get("first_image")
                f2 = request.files.get("second_image")

                # GIỮ NGUYÊN pattern p1, p2
                p1, p2 = save_uploaded_files(f1, f2)

                if p1:
                    all_temp_files.append(p1)
                if p2:
                    all_temp_files.append(p2)

            # ❗ CHỈ FAIL nếu KHÔNG có raw_text và KHÔNG có ảnh
            if not raw_text and not all_temp_files:
                return jsonify({
                    "statusCode": 400,
                    "message": "raw_text or images is required"
                }), 400

            provider = request.form.get("provider", "openai")
            user_id = getattr(g, "user_id", None)

            # ===== 2. Lưu document =====
            doc_id = documents_repo.save_document(
                user_id=user_id,
                doc_type=doc_type,
                filename=(
                    os.path.basename(all_temp_files[0])
                    if all_temp_files else "raw_text_input"
                ),
                status=DocStatus.UPLOADED
            )

            # Check quota
            is_allowed, msg = subscription_service.check_quota(g.user)
            if not is_allowed:
                return jsonify({"statusCode": 403, "message": msg}), 403

            # Increment usage 
            if g.user.get('account_id'):
                accounts_repo.increment_usage(g.user.get('account_id'))

            # ===== 3. Đăng ký lắng nghe TRƯỚC khi gửi task =====
            pubsub = redis_conn.pubsub()
            channel = f"sse_user_{user_id}"
            pubsub.subscribe(channel)

            # ===== 4. Enqueue worker =====
            rag_queue.enqueue(
                process_detection_task,
                args=(doc_id, user_id, doc_type, all_temp_files, provider),
                kwargs={"raw_text": raw_text},
                job_timeout="5m"
            )

            wait_timeout = 10
            start_wait = time.time()
            final_result = None

            # Kiểm tra nhanh DB (Fast-path cho QR)
            doc_check = documents_repo.find_by_id(doc_id)
            if doc_check and doc_check.get("status") == DocStatus.READY:
                final_result = {
                    "statusCode": 200,
                    "message": "Success (Fast-Path)",
                    "data": doc_check.get("result"),
                    "debug": doc_check.get("debug")
                }

            if not final_result:
                while time.time() - start_wait < wait_timeout:
                    message = pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0
                    )

                    if message:
                        try:
                            payload = json.loads(message["data"])
                            data = payload.get("data", {})

                            if str(data.get("document_id")) == str(doc_id):
                                status = data.get("status")

                                if status == DocStatus.READY:
                                    final_result = {
                                        "statusCode": 200,
                                        "message": "Success (Synchronized)",
                                        "data": data.get("result"),
                                        "debug": data.get("debug")
                                    }
                                    break

                                elif status == DocStatus.FAILED:
                                    final_result = {
                                        "statusCode": 500,
                                        "message": f"Processing failed: {data.get('error')}"
                                    }
                                    break
                        except Exception:
                            pass

                    time.sleep(0.1)

            pubsub.unsubscribe(channel)
            pubsub.close()

            if final_result:
                return jsonify(final_result), final_result["statusCode"]

            return jsonify({
                "statusCode": 202,
                "message": "Detection task enqueued (Wait Timeout). Please check status or listen to SSE.",
                "data": {"document_id": doc_id}
            }), 202

        except Exception as e:
            return jsonify({
                "statusCode": 500,
                "message": str(e)
            }), 500



    @app.route("/api/detect", methods=["POST"])
    @require_auth
    def detect():
        try:
            doc_type, error_resp, status_code = validate_request_params(request)
            if error_resp: return error_resp, status_code

            all_temp_files = []
            files = request.files.getlist('files')
            if files:
                from src.utils.file_utils import save_uploaded_file_list
                all_temp_files = save_uploaded_file_list(files)
            else:
                f1 = request.files.get("first_image")
                f2 = request.files.get("second_image")
                p1, p2 = save_uploaded_files(f1, f2)
                if p1: all_temp_files.append(p1)
                if p2: all_temp_files.append(p2)

            user_id = getattr(g, 'user_id', None)
            provider = request.form.get("provider", "openai")
            raw_text = request.form.get("raw_text")

            if not all_temp_files and not raw_text:
                return jsonify({"statusCode": 400, "message": "No images or raw_text provided"}), 400
           
            doc_id = documents_repo.save_document(
                user_id=user_id, doc_type=doc_type,
                filename=os.path.basename(all_temp_files[0]) if all_temp_files else "raw_text_input",
                status=DocStatus.UPLOADED
            )

            # Check quota
            is_allowed, msg = subscription_service.check_quota(g.user)
            if not is_allowed:
                return jsonify({"statusCode": 403, "message": msg}), 403

            # Inform SSE about the new task
            from src.utils.redis_client import publish_event
            publish_event(user_id, "detection_status", {
                "document_id": doc_id,
                "status": DocStatus.UPLOADED,
                "type": doc_type,
                "provider": provider,
                "message": msg
            })

            # Increment usage 
            if g.user.get('account_id'):
                accounts_repo.increment_usage(g.user.get('account_id'))

            rag_queue.enqueue(
                process_detection_task,
                args=(doc_id, user_id, doc_type, all_temp_files, provider),
                kwargs={"raw_text": raw_text},
                job_timeout='5m'
            )

            return jsonify({
                "statusCode": 202,
                "message": "Detection task enqueued",
                "data": {"document_id": doc_id}
            }), 202
        except Exception as e:
            Log.error(f"[API] ❌ Error: {e}")
            return jsonify({"statusCode": 500, "message": str(e)}), 500


    @app.route("/api/corrections/submit", methods=["POST"])
    @require_auth
    def submit_correction():
        """
        API để người dùng map lại kết quả đúng. Hệ thống sẽ học từ đây.
        Payload: {
            "document_id": "xxx",
            "corrected_data": {...}
        }
        """
        try:
            data = request.json
            doc_id = data.get("document_id")
            corrected_data = data.get("corrected_data")

            if not doc_id or not corrected_data:
                return jsonify({"statusCode": 400, "message": "Missing document_id or corrected_data"}), 400

            # 1. Lấy dữ liệu cũ để so sánh
            doc = documents_repo.find_by_id(doc_id)
            if not doc:
                return jsonify({"statusCode": 404, "message": "Document not found"}), 404
            
            old_result = doc.get("result", {})
            doc_type = doc.get("document_type", "unknown")
            user_id = getattr(g, 'user_id', None)

            # 2. So sánh và lưu vào bảng Corrections
            from src.repositories.corrections_repository import corrections_repo
            
            def track_diff(obj1, obj2, prefix=""):
                if not isinstance(obj1, dict) or not isinstance(obj2, dict):
                    return
                
                for key, val2 in obj2.items():
                    val1 = obj1.get(key)
                    field_path = f"{prefix}.{key}" if prefix else key
                    
                    if isinstance(val2, list) and isinstance(val1, list):
                        # So sánh từng phần tử trong list (ví dùng menu_items)
                        for i, (item1, item2) in enumerate(zip(val1, val2)):
                            track_diff(item1, item2, f"{field_path}[{i}]")
                    elif val1 != val2 and val2 is not None:
                        # Log cặp thay đổi
                        corrections_repo.log_correction(
                            doc_type=doc_type,
                            field_name=field_path,
                            original_text=val1,
                            corrected_text=val2,
                            user_id=user_id
                        )

            track_diff(old_result, corrected_data)

            # 3. Cập nhật kết quả vào document để làm giàu dữ liệu (enrichment)
            documents_repo.update_status(doc_id, status=doc.get("status"), result=corrected_data)

            return jsonify({
                "statusCode": 200,
                "message": "Correction submitted and learned successfully"
            }), 200

        except Exception as e:
            Log.error(f"[API] Correction Error: {e}")
            return jsonify({"statusCode": 500, "message": str(e)}), 500

    @app.route("/api/report_extraction", methods=["POST"])
    @require_auth
    def report_extraction():
        """
        API cho phép user report kết quả extract bị sai.
        Payload: {
            "document_id": "xxx",
            "reason": "Sai thông tin tên/ngày sinh...",
            "details": "Tên đúng là Nguyễn Văn A, máy đọc là Nguyễn Văn B" (Optional),
            "extraction_result": {...} (Optional - what the user saw)
        }
        """
        try:
            data = request.json
            doc_id = data.get("document_id")
            reason = data.get("reason")
            details = data.get("details")
            extraction_result = data.get("extraction_result")

            if not doc_id or not reason:
                return jsonify({"statusCode": 400, "message": "Missing document_id or reason"}), 400

            user_id = getattr(g, 'user_id', None)
            
            # Get document info to extract doc_type
            doc_type = None
            try:
                doc_info = documents_repo.find_by_id(doc_id)
                if doc_info:
                    doc_type = doc_info.get("document_type")
            except:
                pass
            
            # Save to dedicated reports collection
            from src.repositories.extraction_reports_repository import extraction_reports_repo
            report_id = extraction_reports_repo.create_report(
                document_id=doc_id,
                user_id=user_id,
                reason=reason,
                details=details,
                extraction_result=extraction_result,
                doc_type=doc_type
            )
            
            # Also update extraction_logs for backward compatibility
            from src.repositories.extraction_logs_repository import extraction_logs_repo
            extraction_logs_repo.update_report(doc_id, reason, details, extraction_result)
            
            Log.info(f"[API] Report created: {report_id} for document: {doc_id}")
            
            return jsonify({
                "statusCode": 200, 
                "message": "Report submitted successfully",
                "data": {"report_id": report_id}
            }), 200

        except Exception as e:
            Log.error(f"[API] Report Error: {e}")
            import traceback
            Log.error(traceback.format_exc())
            return jsonify({"statusCode": 500, "message": str(e)}), 500