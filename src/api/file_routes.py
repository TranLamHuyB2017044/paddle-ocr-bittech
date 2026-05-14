"""
File Routes
API endpoints để xem file ảnh gốc đã lưu trên Cloudinary (private/authenticated).

Endpoints:
  GET  /api/files/<doc_id>/view
       → Owner / Manager: trả signed URL (15 phút).
       → Admin: phải cung cấp break_glass_reason trong body/query.

  POST /api/files/<doc_id>/admin-view
       → Admin only, body: {"reason": "..."}
       → Trả signed URL + ghi audit log.

  GET  /api/files/<doc_id>/audit-log
       → Admin only: xem lịch sử truy cập file của document.

Config workspace:
  PUT  /api/rag/workspaces/<workspace_id>/settings
       → Cập nhật allow_source_file_storage, file_retention_days.
"""
from flask import Blueprint, request, jsonify, g
from src.utils.auth_middleware import require_auth
from src.utils.logger import Log
from src.utils.file_access_control import check_file_access, get_request_context, ROLE_ADMIN
from src.repositories.documents_repository import documents_repo
from src.repositories.file_storage_repository import file_storage_repo
from src.repositories.audit_log_repository import audit_log_repo, AuditEvent
from src.utils.cloudinary_utils import cloudinary_service

file_bp = Blueprint("file_bp", __name__)

# Thời gian signed URL hợp lệ (giây)
SIGNED_URL_EXPIRY_SEC = 15 * 60  # 15 phút


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

    - Owner / Manager: trả signed URL ngay.
    - Admin: phải truyền query param `break_glass_reason`.
    """
    try:
        doc = documents_repo.find_by_id(doc_id)
        if not doc:
            return jsonify({"statusCode": 404, "message": "Document không tồn tại."}), 404

        # Gắn account_id vào doc để RBAC check
        if not doc.get("account_id") and g.user.get("account_id"):
            # Nếu doc chưa có account_id thì kế thừa từ user (backward compat)
            doc["account_id"] = g.user.get("account_id")

        actor_role = g.user.get("role", 2)
        break_glass_reason = request.args.get("break_glass_reason") if actor_role == ROLE_ADMIN else None

        access = check_file_access(g.user, doc, break_glass_reason=break_glass_reason)
        ctx = get_request_context()

        if not access.allowed:
            # Ghi access denied log
            audit_log_repo.log_event(
                event_type=AuditEvent.ACCESS_DENIED,
                actor_user_id=g.user_id,
                actor_role=actor_role,
                target_doc_id=doc_id,
                reason=access.reason,
                **ctx,
            )
            return jsonify({"statusCode": 403, "message": access.reason}), 403

        # Kiểm tra có file metadata không
        signed_files = _build_signed_urls(doc_id)
        if not signed_files:
            return jsonify({
                "statusCode": 404,
                "message": "Không tìm thấy ảnh gốc. File có thể chưa được lưu hoặc đã hết hạn."
            }), 404

        # Ghi audit log
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
    Body JSON: {"reason": "Lý do cụ thể..."}
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

        # Bắt buộc ghi audit log cho mọi lần admin break-glass
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


# ── PUT /api/rag/workspaces/<workspace_id>/settings ───────────────────────────
@file_bp.route("/api/rag/workspaces/<workspace_id>/settings", methods=["PUT"])
@require_auth
def update_workspace_settings(workspace_id: str):
    """
    Cập nhật cấu hình workspace, bao gồm:
      - allow_source_file_storage (bool): có lưu ảnh gốc lên Cloudinary không.
      - file_retention_days (int):        số ngày giữ ảnh trước khi tự xóa.
    """
    try:
        from src.repositories.workspaces_repository import workspaces_repo
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not workspace or workspace["user_id"] != g.user_id:
            return jsonify({"statusCode": 403, "message": "Access denied."}), 403

        data = request.get_json(silent=True) or {}
        update_fields = {}

        if "allow_source_file_storage" in data:
            val = data["allow_source_file_storage"]
            if not isinstance(val, bool):
                return jsonify({"statusCode": 400, "message": "'allow_source_file_storage' phải là boolean."}), 400
            update_fields["allow_source_file_storage"] = val

        if "file_retention_days" in data:
            days = int(data["file_retention_days"])
            if days < 1 or days > 365:
                return jsonify({"statusCode": 400, "message": "'file_retention_days' phải từ 1 đến 365."}), 400
            update_fields["file_retention_days"] = days

        if not update_fields:
            return jsonify({"statusCode": 400, "message": "Không có trường hợp lệ để cập nhật."}), 400

        from datetime import datetime
        update_fields["updated_at"] = datetime.now()
        workspaces_repo.collection.update_one(
            {"_id": __import__("bson").ObjectId(workspace_id)},
            {"$set": update_fields}
        )

        return jsonify({
            "statusCode": 200,
            "message": "Cập nhật cấu hình workspace thành công.",
            "data": update_fields
        }), 200

    except Exception as e:
        Log.error(f"[FileAPI] update_workspace_settings error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500
