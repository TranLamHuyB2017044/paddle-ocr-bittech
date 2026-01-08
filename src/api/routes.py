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

ALLOWED_DOC_TYPES = {'idCard', 'driverLicense', 'invoice', 'document', 'vehicleDocuments'}
MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB limit

def validate_request_params(req):
    """
    Validate request parameters and files
    """
    if req.content_length and req.content_length > MAX_CONTENT_LENGTH:
        return None, jsonify({"statusCode": 413, "message": f"File quá lớn. Giới hạn {MAX_CONTENT_LENGTH/1024/1024}MB"}), 413

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
                status="UPLOADED"
            )

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
                status="UPLOADED"
            )

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
                status="UPLOADED"
            )

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
