"""
API Routes
Định nghĩa các API endpoints cho CCCD OCR (Phiên bản Bất đồng bộ)
"""
import os
from flask import request, jsonify, send_from_directory, g
from src.utils.auth_middleware import require_auth
from src.utils.file_utils import save_uploaded_files
from src.utils.redis_client import rag_queue
from src.tasks.document_tasks import process_detection_task
from src.repositories.documents_repository import documents_repo
from src.utils.logger import Log
from src.config import MAX_OCR_FILE_SIZE, DocStatus

ALLOWED_DOC_TYPES = {'idCard', 'driverLicense', 'invoice', 'document', 'vehicleDocuments'}

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

            return jsonify({
                "statusCode": 200,
                "message": "Success",
                "data": {
                    "total_extractions": total_extractions,
                    "today_extractions": today_extractions,
                    "last_extraction_at": last_extraction_at.isoformat() if last_extraction_at else None,
                    "breakdown": breakdown,
                    "doc_type_stats": breakdown
                }
            }), 200
        except Exception as e:
            Log.error(f"[API] Error fetching user stats: {e}")
            return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500

    @app.route("/api/traditional", methods=["POST"])
    @require_auth
    def detect_traditional():
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

            # Inform SSE about the new task
            from src.utils.redis_client import publish_event
            publish_event(user_id, "detection_status", {
                "document_id": doc_id,
                "status": DocStatus.UPLOADED,
                "type": doc_type,
                "message": "Task received and enqueued"
            })

            rag_queue.enqueue(
                process_detection_task,
                args=(doc_id, user_id, doc_type, all_temp_files, "traditional"),
                job_timeout='5m'
            )

            return jsonify({
                "statusCode": 202,
                "message": "Detection task enqueued",
                "data": {"document_id": doc_id}
            }), 202
        except Exception as e:
            Log.error(f"[API-TRAD] ❌ Error: {e}")
            return jsonify({"statusCode": 500, "message": str(e)}), 500

    @app.route("/api/grok", methods=["POST"])
    @require_auth
    def detect_grok():
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
            doc_id = documents_repo.save_document(
                user_id=user_id, doc_type=doc_type,
                filename=os.path.basename(all_temp_files[0]) if all_temp_files else "unknown",
                status=DocStatus.UPLOADED
            )

            # Inform SSE about the new task
            from src.utils.redis_client import publish_event
            publish_event(user_id, "detection_status", {
                "document_id": doc_id,
                "status": DocStatus.UPLOADED,
                "type": doc_type,
                "message": "Grok task received and enqueued"
            })

            rag_queue.enqueue(
                process_detection_task,
                args=(doc_id, user_id, doc_type, all_temp_files, "grok"),
                job_timeout='5m'
            )

            return jsonify({
                "statusCode": 202,
                "message": "Grok detection enqueued",
                "data": {"document_id": doc_id}
            }), 202
        except Exception as e:
            Log.error(f"[API-GROK] ❌ Error: {e}")
            return jsonify({"statusCode": 500, "message": str(e)}), 500

    @app.route("/api/detect-sync", methods=["POST"])
    @require_auth
    def detect_sync():
        """
        [SYNC-VIA-WORKER] 🕒 Đẩy task xuống worker và CHỜ kết quả qua Redis Pub/Sub.
        Giúp Frontend nhận kết quả ngay lập tức trong 1 request HTTP.
        """
        import time
        import json
        from src.utils.redis_client import redis_conn, publish_event
        
        try:
            doc_type, error_resp, status_code = validate_request_params(request)
            if error_resp: return error_resp, status_code

            # 1. Thu thập file
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

            provider = request.form.get("provider", "traditional")
            user_id = getattr(g, 'user_id', None)

            # 2. Lưu document vào DB (Trạng thái UPLOADED)
            doc_id = documents_repo.save_document(
                user_id=user_id, doc_type=doc_type,
                filename=os.path.basename(all_temp_files[0]),
                status=DocStatus.UPLOADED
            )

            # 3. Đẩy vào Queue cho Worker xử lý
            rag_queue.enqueue(
                process_detection_task,
                args=(doc_id, user_id, doc_type, all_temp_files, provider),
                job_timeout='5m'
            )
            Log.info(f"[SYNC-API] 🚀 Task {doc_id} đã đẩy vào queue. Đang chờ kết quả...")

            # 4. Lắng nghe kết quả qua Redis Pub/Sub (Channel dùng chung cho SSE)
            pubsub = redis_conn.pubsub()
            channel = f"sse_user_{user_id}"
            pubsub.subscribe(channel)
            
            wait_timeout = 120 # Chờ tối đa 120 giây
            start_wait = time.time()
            
            final_result = None
            while time.time() - start_wait < wait_timeout:
                # Kiểm tra message từ Redis (Non-blocking với timeout 1.0s)
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message:
                    try:
                        payload = json.loads(message['data'])
                        data = payload.get("data", {})
                        
                        # Chỉ xử lý nếu đúng ID document đang chờ
                        if str(data.get("document_id")) == str(doc_id):
                            status = data.get("status")
                            
                            if status == DocStatus.READY:
                                Log.info(f"[SYNC-API] ✅ Đã nhận kết quả cho {doc_id}")
                                final_result = {
                                    "statusCode": 200,
                                    "message": "Success (Synchronized)",
                                    "data": data.get("result"),
                                    "debug": data.get("debug")
                                }
                                break
                            elif status == DocStatus.FAILED:
                                Log.error(f"[SYNC-API] ❌ Worker báo lỗi cho {doc_id}")
                                final_result = {
                                    "statusCode": 500,
                                    "message": f"Processing failed: {data.get('error')}"
                                }
                                break
                    except Exception as parse_err:
                        Log.debug(f"[SYNC-API] Skip event không hợp lệ: {parse_err}")
                
                time.sleep(0.1)

            pubsub.unsubscribe(channel)
            
            if final_result:
                return jsonify(final_result), final_result["statusCode"]
            else:
                Log.warning(f"[SYNC-API] ⏳ Hết thời gian chờ (Timeout) cho {doc_id}")
                return jsonify({
                    "statusCode": 504,
                    "message": "Processing timeout. Task vẫn đang chạy dưới nền.",
                    "data": {"document_id": doc_id}
                }), 504

        except Exception as e:
            Log.error(f"[SYNC-API] ❌ Lỗi: {e}")
            return jsonify({"statusCode": 500, "message": str(e)}), 500

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
            provider = request.form.get("provider", "grok")
            
            doc_id = documents_repo.save_document(
                user_id=user_id, doc_type=doc_type,
                filename=os.path.basename(all_temp_files[0]) if all_temp_files else "unknown",
                status=DocStatus.UPLOADED
            )

            # Inform SSE about the new task
            from src.utils.redis_client import publish_event
            publish_event(user_id, "detection_status", {
                "document_id": doc_id,
                "status": DocStatus.UPLOADED,
                "type": doc_type,
                "provider": provider,
                "message": "Task received and enqueued"
            })

            rag_queue.enqueue(
                process_detection_task,
                args=(doc_id, user_id, doc_type, all_temp_files, provider),
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
