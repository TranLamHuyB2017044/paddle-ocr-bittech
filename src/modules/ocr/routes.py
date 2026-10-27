"""
File & Document OCR Routes
API Endpoints cho quản lý file, xem file gốc (authenticated & admin break-glass), và xử lý OCR tài liệu (Async & Sync).
"""
import os
import time
import json
from flask import Blueprint, request, jsonify, g
from flasgger import swag_from
from src.core.swagger import DOCS_DIR
from src.shared.utils.auth_middleware import require_auth
from src.shared.utils.logger import Log
from src.shared.utils.file_access_control import check_file_access, get_request_context, ROLE_ADMIN
from src.shared.utils.rate_limit import get_limiter
from src.shared.utils.file_utils import save_uploaded_files, save_uploaded_file_list
from src.shared.utils.redis_client import redis_conn, rag_queue, publish_event
from src.modules.ocr.repositories.documents_repository import documents_repo
from src.modules.ocr.repositories.file_storage_repository import file_storage_repo
from src.modules.auth.repositories.audit_log_repository import audit_log_repo, AuditEvent
from src.modules.auth.repositories.accounts_repository import accounts_repo
from src.shared.utils.cloudinary_utils import cloudinary_service
from src.core.config import MAX_OCR_FILE_SIZE, DocStatus
from src.shared.services.subscription_service import subscription_service
from src.shared.tasks.document_tasks import process_detection_task, process_structure_detection_task

file_bp = Blueprint("file_bp", __name__)
limiter = get_limiter()

# Thời gian signed URL hợp lệ (giây)
SIGNED_URL_EXPIRY_SEC = 15 * 60  # 15 phút
ALLOWED_DOC_TYPES = {'idCard', 'driverLicense', 'invoice', 'vehicleDocuments', 'menu', 'administrativeDocument', 'survey_form'}


@file_bp.route('/uploads/<path:filename>', methods=['GET'])
def serve_uploaded_file(filename):
    """
    Serve file từ uploads/: truy cập công khai (public).
    """
    from flask import send_from_directory, current_app

    upload_folder = current_app.config.get("UPLOAD_FOLDER", "uploads")
    return send_from_directory(upload_folder, filename)


def validate_request_params(req):
    """
    Validate request parameters and files for OCR processing
    """
    if req.content_length and req.content_length > MAX_OCR_FILE_SIZE:
        return None, jsonify({"statusCode": 413, "message": f"File quá lớn. Giới hạn {MAX_OCR_FILE_SIZE/1024/1024}MB"}), 413

    doc_type = req.form.get("type")
    
    if not doc_type:
        return None, jsonify({"statusCode": 400, "message": f"Missing 'type' parameter. Required one of: {sorted(list(ALLOWED_DOC_TYPES))}"}), 400
 
    if doc_type not in ALLOWED_DOC_TYPES:
        return None, jsonify({"statusCode": 400, "message": f"Loại giấy tờ không hợp lệ. Cho phép: {ALLOWED_DOC_TYPES}"}), 400

    return doc_type, None, None


def _build_signed_urls(doc_id: str) -> list[dict]:
    """Lấy tất cả file records của document và tạo signed URL."""
    records = file_storage_repo.find_by_document(doc_id)
    result = []
    for r in records:
        signed_url = cloudinary_service.generate_signed_url(
            public_id=r["cloudinary_public_id"],
            resource_type=r.get("resource_type", "image"),
            expires_in_seconds=SIGNED_URL_EXPIRY_SEC,
        )
        result.append({
            "original_filename": r.get("original_filename"),
            "signed_url": signed_url,
            "expires_in": f"{SIGNED_URL_EXPIRY_SEC // 60} phút",
            "expires_at": r.get("expires_at").isoformat() if r.get("expires_at") else None,
        })
    return result


# ── GET /api/files/<doc_id>/view ───────────────────────────────────────────────
@file_bp.route("/api/files/<doc_id>/view", methods=["GET"])
@require_auth
def view_file(doc_id: str):
    """
    Xem file ảnh gốc của document.
    """
    try:
        doc = documents_repo.find_by_id(doc_id)
        if not doc:
            return jsonify({"statusCode": 404, "message": "Document không tồn tại."}), 404

        if not doc.get("account_id") and g.user.get("account_id"):
            doc["account_id"] = g.user.get("account_id")

        actor_role = g.user.get("role", 2)
        break_glass_reason = request.args.get("break_glass_reason") if actor_role == ROLE_ADMIN else None

        access = check_file_access(g.user, doc, break_glass_reason=break_glass_reason)
        ctx = get_request_context()

        if not access.allowed:
            audit_log_repo.log_event(
                event_type=AuditEvent.ACCESS_DENIED,
                actor_user_id=g.user_id,
                actor_role=actor_role,
                target_doc_id=doc_id,
                reason=access.reason,
                **ctx,
            )
            return jsonify({"statusCode": 403, "message": access.reason}), 403

        signed_files = _build_signed_urls(doc_id)
        if not signed_files:
            return jsonify({
                "statusCode": 404,
                "message": "Không tìm thấy ảnh gốc. File có thể chưa được lưu hoặc đã hết hạn."
            }), 404

        event_type = AuditEvent.ADMIN_BREAK_GLASS if access.require_audit else AuditEvent.FILE_VIEWED
        audit_log_repo.log_event(
            event_type=event_type,
            actor_user_id=g.user_id,
            actor_role=actor_role,
            target_doc_id=doc_id,
            target_file=doc_id,
            reason=break_glass_reason,
            metadata={"file_count": len(signed_files)},
            **ctx,
        )

        return jsonify({
            "statusCode": 200,
            "message": "OK",
            "data": {
                "document_id": doc_id,
                "files": signed_files,
                "note": "URL hết hạn sau 15 phút." if signed_files else None,
            }
        }), 200

    except Exception as e:
        Log.error(f"[FileAPI] view_file error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── POST /api/files/<doc_id>/admin-view ───────────────────────────────────────
@file_bp.route("/api/files/<doc_id>/admin-view", methods=["POST"])
@require_auth
def admin_view_file(doc_id: str):
    """
    Admin break-glass: xem file người dùng khác.
    """
    try:
        actor_role = g.user.get("role", 2)
        if actor_role != ROLE_ADMIN:
            return jsonify({"statusCode": 403, "message": "Chỉ Admin mới có thể dùng tính năng này."}), 403

        data = request.get_json(silent=True) or {}
        reason = (data.get("reason") or "").strip()

        if not reason:
            return jsonify({
                "statusCode": 400,
                "message": "Bắt buộc cung cấp 'reason' khi admin xem file của người dùng khác."
            }), 400

        doc = documents_repo.find_by_id(doc_id)
        if not doc:
            return jsonify({"statusCode": 404, "message": "Document không tồn tại."}), 404

        access = check_file_access(g.user, doc, break_glass_reason=reason)
        ctx = get_request_context()

        if not access.allowed:
            return jsonify({"statusCode": 403, "message": access.reason}), 403

        signed_files = _build_signed_urls(doc_id)
        if not signed_files:
            return jsonify({
                "statusCode": 404,
                "message": "Không tìm thấy ảnh gốc. File có thể đã hết hạn hoặc chưa được lưu."
            }), 404

        audit_log_repo.log_event(
            event_type=AuditEvent.ADMIN_BREAK_GLASS,
            actor_user_id=g.user_id,
            actor_role=ROLE_ADMIN,
            target_doc_id=doc_id,
            target_file=doc_id,
            reason=reason,
            metadata={
                "doc_owner": str(doc.get("user_id")),
                "file_count": len(signed_files),
            },
            **ctx,
        )

        Log.warning(
            f"[FileAPI] 🔓 ADMIN BREAK-GLASS: admin={g.user_id} "
            f"doc={doc_id} owner={doc.get('user_id')} reason={reason!r}"
        )

        return jsonify({
            "statusCode": 200,
            "message": "Break-glass access granted. Hành động này đã được ghi lại.",
            "data": {
                "document_id": doc_id,
                "files": signed_files,
                "audit": {"reason": reason, "actor": g.user_id},
            }
        }), 200

    except Exception as e:
        Log.error(f"[FileAPI] admin_view_file error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── GET /api/files/<doc_id>/audit-log ─────────────────────────────────────────
@file_bp.route("/api/files/<doc_id>/audit-log", methods=["GET"])
@require_auth
def get_audit_log(doc_id: str):
    """
    Admin only: xem lịch sử truy cập file của một document.
    """
    try:
        actor_role = g.user.get("role", 2)
        if actor_role != ROLE_ADMIN:
            return jsonify({"statusCode": 403, "message": "Chỉ Admin mới có thể xem audit log."}), 403

        limit = request.args.get("limit", 50, type=int)
        logs = audit_log_repo.find_by_document(doc_id, limit=limit)

        for log in logs:
            log["_id"] = str(log["_id"])
            if log.get("timestamp"):
                log["timestamp"] = log["timestamp"].isoformat()

        return jsonify({
            "statusCode": 200,
            "data": {"document_id": doc_id, "logs": logs, "count": len(logs)}
        }), 200

    except Exception as e:
        Log.error(f"[FileAPI] get_audit_log error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── POST /api/traditional ──────────────────────────────────────────────────────
@file_bp.route("/api/traditional", methods=["POST"])
@require_auth
@limiter.limit("30 per minute")
def detect_traditional():
    try:
        doc_type, error_resp, status_code = validate_request_params(request)
        if error_resp: return error_resp, status_code

        all_temp_files = []
        files = request.files.getlist('files')
        if files:
            all_temp_files = save_uploaded_file_list(files)
        else:
            f1 = request.files.get("first_image")
            f2 = request.files.get("second_image")
            p1, p2 = save_uploaded_files(f1, f2)
            if p1: all_temp_files.append(p1)
            if p2: all_temp_files.append(p2)

        if not all_temp_files:
            return jsonify({"statusCode": 400, "message": "No images provided"}), 400

        source_files_meta = [
            {
                "file_name": os.path.basename(p),
                "storage_path": p.replace("\\", "/")
            }
            for p in all_temp_files
        ]

        user_id = getattr(g, 'user_id', None)
        doc_id = documents_repo.save_document(
            user_id=user_id, doc_type=doc_type,
            filename=os.path.basename(all_temp_files[0]),
            status=DocStatus.UPLOADED,
            source_files=source_files_meta
        )

        detect_handwriting = request.form.get("detect_handwriting", "false").lower() == "true"
        vision_extract = request.form.get("vision_extract", "false").lower() == "true"
        cost = 3 if vision_extract else 1

        is_allowed, msg = subscription_service.check_quota(g.user, cost=cost)
        if not is_allowed:
            return jsonify({"statusCode": 403, "message": msg}), 403

        pubsub = redis_conn.pubsub()
        channel = f"sse_user_{user_id}"
        pubsub.subscribe(channel)

        publish_event(user_id, "detection_status", {
            "document_id": doc_id,
            "status": DocStatus.UPLOADED,
            "type": doc_type,
            "message": msg
        })

        if g.user.get('account_id'):
            accounts_repo.increment_usage(g.user.get('account_id'), amount=cost)

        rag_queue.enqueue(
            process_detection_task,
            args=(doc_id, user_id, doc_type, all_temp_files, "traditional"),
            kwargs={"detect_handwriting": detect_handwriting, "vision_extract": vision_extract},
            job_timeout='5m'
        )

        wait_timeout = 300
        start_wait = time.time()
        final_result = None

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
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
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


# ── GET /api/document/<doc_id> ─────────────────────────────────────────────────
@file_bp.route("/api/document/<doc_id>", methods=["GET"])
@require_auth
@swag_from(str(DOCS_DIR / "ocr" / "document_status.yml"))
def get_document_status(doc_id: str):
    """
    Get document status and results
    """
    try:
        doc = documents_repo.find_by_id(doc_id)
        if not doc:
            return jsonify({"statusCode": 404, "message": "Document not found"}), 404
        
        if str(doc.get("user_id")) != str(g.user_id):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403
        
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


# ── POST /api/detect-sync ──────────────────────────────────────────────────────
@file_bp.route("/api/detect-sync", methods=["POST"])
@require_auth
@limiter.limit("30 per minute")
def detect_sync():
    """
    Synchronous document detection via worker.
    """
    try:
        doc_type, error_resp, status_code = validate_request_params(request)
        if error_resp:
            return error_resp, status_code

        raw_text = request.form.get("raw_text")
        all_temp_files = []
        files = request.files.getlist("files")
        if files and len(files) > 0:
            all_temp_files = save_uploaded_file_list(files)
        else:
            f1 = request.files.get("first_image")
            f2 = request.files.get("second_image")
            p1, p2 = save_uploaded_files(f1, f2)
            if p1: all_temp_files.append(p1)
            if p2: all_temp_files.append(p2)

        if not raw_text and not all_temp_files:
            return jsonify({"statusCode": 400, "message": "raw_text or images is required"}), 400

        provider = request.form.get("provider", "openai")
        user_id = getattr(g, "user_id", None)
        detect_handwriting = request.form.get("detect_handwriting", "false").lower() == "true"
        vision_extract = request.form.get("vision_extract", "false").lower() == "true"

        source_files_meta = [
            {
                "file_name": os.path.basename(p),
                "storage_path": p.replace("\\", "/")
            }
            for p in all_temp_files
        ] if all_temp_files else []

        doc_id = documents_repo.save_document(
            user_id=user_id,
            doc_type=doc_type,
            filename=os.path.basename(all_temp_files[0]) if all_temp_files else "raw_text_input",
            status=DocStatus.UPLOADED,
            source_files=source_files_meta
        )

        cost = 3 if vision_extract else 1

        is_allowed, msg = subscription_service.check_quota(g.user, cost=cost)
        if not is_allowed:
            return jsonify({"statusCode": 403, "message": msg}), 403

        if g.user.get('account_id'):
            accounts_repo.increment_usage(g.user.get('account_id'), amount=cost)

        pubsub = redis_conn.pubsub()
        channel = f"sse_user_{user_id}"
        pubsub.subscribe(channel)

        task_func = process_structure_detection_task if doc_type in ['invoice', 'menu'] else process_detection_task

        rag_queue.enqueue(
            task_func,
            args=(doc_id, user_id, doc_type, all_temp_files, provider),
            kwargs={"raw_text": raw_text, "detect_handwriting": detect_handwriting, "vision_extract": vision_extract},
            job_timeout="5m"
        )

        wait_timeout = 300
        start_wait = time.time()
        final_result = None

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
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
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
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── POST /api/detect ───────────────────────────────────────────────────────────
@file_bp.route("/api/detect", methods=["POST"])
@require_auth
@limiter.limit("30 per minute")
def detect():
    try:
        doc_type, error_resp, status_code = validate_request_params(request)
        if error_resp: return error_resp, status_code

        all_temp_files = []
        files = request.files.getlist('files')
        if files:
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
        detect_handwriting = request.form.get("detect_handwriting", "false").lower() == "true"
        vision_extract = request.form.get("vision_extract", "false").lower() == "true"

        if not all_temp_files and not raw_text:
            return jsonify({"statusCode": 400, "message": "No images or raw_text provided"}), 400

        source_files_meta = [
            {
                "file_name": os.path.basename(p),
                "storage_path": p.replace("\\", "/")
            }
            for p in all_temp_files
        ] if all_temp_files else []

        doc_id = documents_repo.save_document(
            user_id=user_id, doc_type=doc_type,
            filename=os.path.basename(all_temp_files[0]) if all_temp_files else "raw_text_input",
            status=DocStatus.UPLOADED,
            source_files=source_files_meta
        )

        cost = 3 if vision_extract else 1

        is_allowed, msg = subscription_service.check_quota(g.user, cost=cost)
        if not is_allowed:
            return jsonify({"statusCode": 403, "message": msg}), 403

        publish_event(user_id, "detection_status", {
            "document_id": doc_id,
            "status": DocStatus.UPLOADED,
            "type": doc_type,
            "provider": provider,
            "message": msg
        })

        if g.user.get('account_id'):
            accounts_repo.increment_usage(g.user.get('account_id'), amount=cost)

        task_func = process_structure_detection_task if doc_type in ['invoice', 'menu'] else process_detection_task

        rag_queue.enqueue(
            task_func,
            args=(doc_id, user_id, doc_type, all_temp_files, provider),
            kwargs={"raw_text": raw_text, "detect_handwriting": detect_handwriting, "vision_extract": vision_extract},
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
