"""
Chatbot Category Module Routes
Quản lý Category / Chuyên mục tri thức phục vụ cho Chatbot.
"""
from flask import Blueprint, request, jsonify, g
from src.shared.utils.auth_middleware import require_auth
from src.modules.auth.repositories.workspaces_repository import workspaces_repo
from src.modules.chatbot.repositories import chatbot_repo, category_repo
from src.modules.ocr.repositories.documents_repository import documents_repo
from src.shared.repositories.audit_log_repository import audit_log_repo
from src.modules.rag.qdrant_service import qdrant_service
from src.modules.rag.rag_service import rag_service
from src.shared.utils.logger import Log

category_bp = Blueprint('category_bp', __name__)

def _can_access_workspace(workspace):
    """Kiểm tra quyền sở hữu workspace, cùng account_id hoặc quyền admin (role 0)"""
    if not workspace:
        return False
    user = getattr(g, 'user', None)
    if user and user.get('role') == 0:
        return True
    
    # So sánh user_id (ép kiểu chuỗi để tương thích cả ObjectId và string)
    ws_user_id = str(workspace.get('user_id')) if workspace.get('user_id') else None
    if ws_user_id and ws_user_id == str(g.user_id):
        return True

    # Cho phép truy cập nếu cùng account_id (tài khoản công ty/tổ chức)
    user_account_id = str(user.get('account_id')) if user and user.get('account_id') else None
    ws_account_id = str(workspace.get('account_id')) if workspace.get('account_id') else None
    if user_account_id and ws_account_id and user_account_id == ws_account_id:
        return True

    return False

# ── 1. GET WORKSPACE CATEGORIES ──────────────────────────────────────────────
@category_bp.route('/api/chatbot/workspaces/<workspace_id>/categories', methods=['GET'])
@require_auth
def list_workspace_categories(workspace_id):
    try:
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not _can_access_workspace(workspace):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        categories = category_repo.list_by_workspace(workspace_id, include_deleted=False)
        for cat in categories:
            cat["doc_count"] = documents_repo.count_by_workspace(workspace_id, category=cat["slug"])

        return jsonify({"statusCode": 200, "data": categories}), 200
    except Exception as e:
        Log.error(f"[CategoryAPI] List categories error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── 2. CREATE CATEGORY ───────────────────────────────────────────────────────
@category_bp.route('/api/chatbot/workspaces/<workspace_id>/categories', methods=['POST'])
@require_auth
def create_workspace_category(workspace_id):
    try:
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not _can_access_workspace(workspace):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"statusCode": 400, "message": "Trường 'name' là bắt buộc"}), 400

        description = data.get("description")
        icon = data.get("icon")

        try:
            new_cat = category_repo.create_category(
                workspace_id=workspace_id,
                name=name,
                description=description,
                icon=icon,
                created_by=g.user_id
            )
        except ValueError as ve:
            return jsonify({"statusCode": 409, "message": str(ve)}), 409

        # Audit log
        audit_log_repo.log(
            action="category.create",
            actor_user_id=g.user_id,
            account_id=g.user.get("account_id"),
            workspace_id=workspace_id,
            target_type="category",
            target_id=new_cat["slug"],
            snapshot=new_cat,
            ip=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )

        return jsonify({"statusCode": 201, "message": "Tạo category thành công", "data": new_cat}), 201
    except Exception as e:
        Log.error(f"[CategoryAPI] Create category error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── 3. UPDATE CATEGORY ───────────────────────────────────────────────────────
@category_bp.route('/api/chatbot/workspaces/<workspace_id>/categories/<slug>', methods=['PUT'])
@require_auth
def update_workspace_category(workspace_id, slug):
    try:
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not _can_access_workspace(workspace):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        cat = category_repo.find_active_by_slug(workspace_id, slug)
        if not cat:
            return jsonify({"statusCode": 404, "message": f"Category '{slug}' không tồn tại"}), 404

        data = request.get_json(silent=True) or {}
        name = data.get("name")
        description = data.get("description")
        icon = data.get("icon")

        try:
            updated_cat = category_repo.update_category(
                workspace_id=workspace_id,
                slug=slug,
                name=name,
                description=description,
                icon=icon
            )
        except ValueError as ve:
            return jsonify({"statusCode": 409, "message": str(ve)}), 409

        if not updated_cat:
            return jsonify({"statusCode": 404, "message": f"Category '{slug}' không tìm thấy để cập nhật"}), 404

        old_slug = slug
        new_slug = updated_cat.get("slug", old_slug)
        affected_docs_count = 0

        # Cascade update nếu slug thay đổi theo tên category
        if new_slug != old_slug:
            # 1. Update documents in MongoDB
            affected_docs_count = documents_repo.rename_category(workspace_id, old_slug, new_slug)
            Log.info(f"[CategoryAPI] Cascade renamed category '{old_slug}' -> '{new_slug}' for {affected_docs_count} documents")

            # 2. Update vector payload in Qdrant
            try:
                qdrant_service.rename_category(workspace_id, old_slug, new_slug)
                Log.info(f"[CategoryAPI] Cascade updated Qdrant payload category '{old_slug}' -> '{new_slug}' in workspace '{workspace_id}'")
            except Exception as q_err:
                Log.error(f"[CategoryAPI] Failed to update Qdrant payload category: {q_err}")

        # Xóa trường nội bộ nếu có
        updated_cat.pop("_old_slug", None)

        audit_log_repo.log(
            action="category.update",
            actor_user_id=g.user_id,
            account_id=g.user.get("account_id"),
            workspace_id=workspace_id,
            target_type="category",
            target_id=new_slug,
            snapshot={"old": cat, "updated": updated_cat},
            affected={"old_slug": old_slug, "new_slug": new_slug, "affected_documents": affected_docs_count},
            ip=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )

        return jsonify({
            "statusCode": 200,
            "message": "Cập nhật category thành công",
            "data": updated_cat,
            "affected_documents": affected_docs_count
        }), 200
    except Exception as e:
        Log.error(f"[CategoryAPI] Update category error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── 4. DELETE CATEGORY (CASCADE SOFT-DELETE + AUDIT) ───────────────────────────
@category_bp.route('/api/chatbot/workspaces/<workspace_id>/categories/<slug>', methods=['DELETE'])
@require_auth
def delete_workspace_category(workspace_id, slug):
    try:
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not _can_access_workspace(workspace):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        cat = category_repo.find_active_by_slug(workspace_id, slug)
        if not cat:
            return jsonify({"statusCode": 404, "message": f"Category '{slug}' không tồn tại"}), 404

        confirm = request.args.get('confirm', 'false').lower() == 'true'
        doc_count = documents_repo.count_by_workspace(workspace_id, category=slug)

        if not confirm:
            return jsonify({
                "statusCode": 400,
                "message": f"Xóa category '{cat['name']}' sẽ xóa {doc_count} tài liệu thuộc category này. Vui lòng truyền confirm=true để xác nhận.",
                "data": {
                    "slug": slug,
                    "name": cat["name"],
                    "affected_documents": doc_count,
                    "requires_confirm": True
                }
            }), 400

        body_data = request.get_json(silent=True) or {}
        reason = request.args.get('reason') or body_data.get('reason')

        # 1. Hard delete vector points from Qdrant first
        try:
            qdrant_service.delete_by_category(workspace_id, slug)
            Log.info(f"[CategoryAPI] Deleted vector points for category '{slug}' in workspace '{workspace_id}'")
        except Exception as q_err:
            Log.error(f"[CategoryAPI] Failed to delete Qdrant vectors for category '{slug}': {q_err}")
            return jsonify({"statusCode": 500, "message": f"Lỗi xóa vector: {str(q_err)}"}), 500

        # 2. Soft-delete all documents in MongoDB
        affected_docs = documents_repo.soft_delete_by_category(workspace_id, slug, deleted_by=g.user_id)
        affected_doc_ids = [str(d["_id"]) for d in affected_docs]

        # 3. Soft-delete category in MongoDB
        deleted_cat = category_repo.soft_delete(workspace_id, slug, deleted_by=g.user_id)

        # 4. Insert Audit Log
        audit_log_repo.log(
            action="category.delete",
            actor_user_id=g.user_id,
            account_id=g.user.get("account_id"),
            workspace_id=workspace_id,
            target_type="category",
            target_id=slug,
            snapshot=cat,
            affected={
                "document_ids": affected_doc_ids,
                "document_count": len(affected_doc_ids),
                "vector_points_deleted": True
            },
            reason=reason,
            ip=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )

        Log.info(f"[CategoryAPI] Successfully deleted category '{slug}' and cascaded soft delete to {len(affected_doc_ids)} docs")
        return jsonify({
            "statusCode": 200,
            "message": f"Đã xóa category '{cat['name']}' và {len(affected_doc_ids)} tài liệu liên quan",
            "data": {
                "slug": slug,
                "deleted_documents_count": len(affected_doc_ids),
                "deleted_document_ids": affected_doc_ids
            }
        }), 200
    except Exception as e:
        Log.error(f"[CategoryAPI] Delete category error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── 5. ADMIN RESTORE CATEGORY ────────────────────────────────────────────────
@category_bp.route('/api/admin/workspaces/<workspace_id>/categories/<slug>/restore', methods=['POST'])
@require_auth
def restore_category_admin(workspace_id, slug):
    try:
        # Admin only check (role == 0)
        if g.user.get("role") != 0:
            return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403

        # 1. Restore category record
        try:
            restored_cat = category_repo.restore(workspace_id, slug)
        except ValueError as ve:
            return jsonify({"statusCode": 409, "message": str(ve)}), 409

        if not restored_cat:
            return jsonify({"statusCode": 404, "message": f"Category '{slug}' không ở trạng thái đã xóa"}), 404

        # 2. Restore soft-deleted documents
        restored_docs = documents_repo.restore_by_category(workspace_id, slug)

        # 3. Re-index restored documents into Qdrant from raw_text
        reindexed_count = 0
        failed_count = 0
        for doc in restored_docs:
            doc_id = str(doc["_id"])
            raw_text = doc.get("raw_text")
            doc_name = doc.get("filename", "Văn bản")
            if raw_text and raw_text.strip():
                try:
                    structured_data = [{"text": raw_text, "page_num": 1}]
                    chunks = rag_service.index_text(
                        structured_data,
                        workspace_id,
                        doc_name,
                        category=slug,
                        document_id=doc_id
                    )
                    documents_repo.update_status(doc_id, "ready", total_chunks=chunks)
                    reindexed_count += 1
                except Exception as idx_err:
                    Log.error(f"[Admin Restore] Failed to reindex doc {doc_id}: {idx_err}")
                    failed_count += 1

        # 4. Audit Log
        audit_log_repo.log(
            action="category.restore",
            actor_user_id=g.user_id,
            account_id=g.user.get("account_id"),
            workspace_id=workspace_id,
            target_type="category",
            target_id=slug,
            snapshot=restored_cat,
            affected={
                "restored_document_count": len(restored_docs),
                "reindexed_count": reindexed_count,
                "reindex_failed_count": failed_count
            },
            ip=request.remote_addr,
            user_agent=request.headers.get("User-Agent")
        )

        return jsonify({
            "statusCode": 200,
            "message": f"Khôi phục category '{restored_cat['name']}' thành công",
            "data": {
                "category": restored_cat,
                "restored_documents": len(restored_docs),
                "reindexed_count": reindexed_count,
                "failed_reindex_count": failed_count
            }
        }), 200
    except Exception as e:
        Log.error(f"[Admin Restore] Error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── 6. ADMIN GET DELETED CATEGORIES ──────────────────────────────────────────
@category_bp.route('/api/admin/workspaces/<workspace_id>/categories/deleted', methods=['GET'])
@require_auth
def list_deleted_categories_admin(workspace_id):
    try:
        if g.user.get("role") != 0:
            return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403

        all_cats = category_repo.list_by_workspace(workspace_id, include_deleted=True)
        deleted = [c for c in all_cats if c.get("is_deleted")]
        return jsonify({"statusCode": 200, "data": deleted}), 200
    except Exception as e:
        Log.error(f"[Admin Deleted Cats] Error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── 7. GET AUDIT LOGS FOR WORKSPACE ──────────────────────────────────────────
@category_bp.route('/api/chatbot/workspaces/<workspace_id>/audit-logs', methods=['GET'])
@require_auth
def list_workspace_audit_logs(workspace_id):
    try:
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not _can_access_workspace(workspace):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        action = request.args.get('action')
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 20, type=int)

        logs, total = audit_log_repo.get_logs_by_workspace(workspace_id, action=action, page=page, limit=limit)
        return jsonify({
            "statusCode": 200,
            "data": {
                "logs": logs,
                "pagination": {
                    "page": page,
                    "limit": limit,
                    "total": total
                }
            }
        }), 200
    except Exception as e:
        Log.error(f"[CategoryAPI] List audit logs error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── 8. PUBLIC CATEGORIES ENDPOINT (FOR WIDGET) ───────────────────────────────
@category_bp.route('/api/public/chatbot/<chatbot_id>/categories', methods=['GET'])
def get_public_chatbot_categories(chatbot_id):
    try:
        public_token = request.headers.get('x-public-token')
        if not public_token:
            return jsonify({"statusCode": 401, "message": "Missing x-public-token header"}), 401

        chatbot = chatbot_repo.find_by_public_token(public_token)
        if not chatbot or str(chatbot["_id"]) != chatbot_id:
            return jsonify({"statusCode": 403, "message": "Invalid chatbot or token"}), 403

        workspace_id = chatbot.get("workspace_id")
        if not workspace_id:
            return jsonify({"statusCode": 200, "data": []}), 200

        categories = category_repo.list_by_workspace(str(workspace_id), include_deleted=False)
        result = []
        for cat in categories:
            count = documents_repo.count_by_workspace(str(workspace_id), category=cat["slug"])
            # Chỉ hiển thị cho bot widget nếu danh mục có ít nhất 1 tài liệu
            if count >= 1:
                result.append({
                    "slug": cat["slug"],
                    "name": cat["name"],
                    "icon": cat.get("icon"),
                    "doc_count": count
                })

        return jsonify({"statusCode": 200, "data": result}), 200
    except Exception as e:
        Log.error(f"[Public Categories] Error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500
