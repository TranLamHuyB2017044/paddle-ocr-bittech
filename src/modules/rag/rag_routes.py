from flask import Blueprint, request, jsonify, g
import os
from src.shared.utils.auth_middleware import require_auth
from src.modules.auth.repositories.workspaces_repository import workspaces_repo
from src.modules.chatbot.repositories.chat_history_repository import chat_history_repo
from src.modules.ocr.repositories.documents_repository import documents_repo
from src.modules.ocr.repositories.extraction_logs_repository import extraction_logs_repo
from src.modules.rag.rag_service import rag_service
from src.modules.rag.qdrant_service import qdrant_service
from src.shared.utils.redis_client import rag_queue
from src.shared.tasks.document_tasks import process_document_task
from src.shared.utils.logger import Log
from src.core.config import MAX_RAG_FILE_SIZE, MAX_FILE_COUNT, MAX_DOCUMENTS_PER_WORKSPACE, DocStatus
from src.shared.services.subscription_service import subscription_service
from src.modules.auth.repositories.accounts_repository import accounts_repo
from src.modules.rag.repositories.category_repository import category_repo
from src.shared.repositories.audit_log_repository import audit_log_repo

rag_bp = Blueprint('rag_bp', __name__)

def _can_access_workspace(workspace):
    """Kiểm tra quyền truy cập workspace: chủ sở hữu hoặc admin (role 0)"""
    if not workspace:
        return False
    user = getattr(g, 'user', None)
    if user and user.get('role') == 0:
        return True
    return workspace.get('user_id') == g.user_id

def _can_access_document(doc):
    """Kiểm tra quyền truy cập document: chủ sở hữu hoặc admin (role 0)"""
    if not doc:
        return False
    user = getattr(g, 'user', None)
    if user and user.get('role') == 0:
        return True
    return str(doc.get('user_id')) == g.user_id

@rag_bp.route('/api/rag/workspaces', methods=['POST'])
@require_auth
def create_workspace():
    try:
        data = request.json
        name = data.get('name')
        description = data.get('description', '')
        
        if not name:
            return jsonify({"statusCode": 400, "message": "Workspace name is required"}), 400
            
        workspace_id = workspaces_repo.create_workspace(name, g.user_id, description)
        
        return jsonify({
            "statusCode": 201,
            "message": "Workspace created successfully",
            "data": {"workspace_id": workspace_id}
        }), 201
    except Exception as e:
        Log.error(f"[RAG-API] Create workspace failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces', methods=['GET'])
@require_auth
def list_workspaces():
    try:
        user = getattr(g, 'user', None)
        if user and user.get('role') == 0:
            workspaces = workspaces_repo.find_all_workspaces()
        else:
            workspaces = workspaces_repo.find_by_user(g.user_id)
        
        # Add document count from Qdrant for each workspace
        for ws in workspaces:
            try:
                ws["document_count"] = qdrant_service.get_document_count(ws["_id"])
            except:
                ws["document_count"] = 0
                
        return jsonify({
            "statusCode": 200,
            "data": workspaces
        })
    except Exception as e:
        Log.error(f"[RAG-API] List workspaces failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces/<workspace_id>', methods=['GET'])
@require_auth
def get_workspace_details(workspace_id):
    try:
        # Verify workspace belongs to user or admin
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not _can_access_workspace(workspace):
            return jsonify({"statusCode": 403, "message": "Access denied or workspace not found"}), 403
            
        # Add extra info
        try:
            workspace["document_count"] = qdrant_service.get_document_count(workspace_id)
        except:
            workspace["document_count"] = 0
            
        # Add documents list
        try:
            documents = list(documents_repo.find_by_workspace(workspace_id))
            for doc in documents:
                doc["_id"] = str(doc["_id"])
                if "user_id" in doc: doc["user_id"] = str(doc["user_id"])
                if "workspace_id" in doc: doc["workspace_id"] = str(doc["workspace_id"])
            workspace["documents"] = documents
        except Exception as doc_err:
            Log.error(f"[RAG-API] Failed to fetch documents for workspace {workspace_id}: {doc_err}")
            workspace["documents"] = []
            
        return jsonify({
            "statusCode": 200,
            "data": workspace
        })
    except Exception as e:
        Log.error(f"[RAG-API] Get workspace failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces/<workspace_id>', methods=['PUT'])
@require_auth
def update_workspace(workspace_id):
    try:
        # Verify workspace belongs to user or admin
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not _can_access_workspace(workspace):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        data = request.json
        name = data.get('name')
        description = data.get('description')
        
        if not name and description is None:
            return jsonify({"statusCode": 400, "message": "Name or description is required"}), 400
            
        success = workspaces_repo.update_workspace(workspace_id, name, description)
        
        if success:
            return jsonify({
                "statusCode": 200,
                "message": "Workspace updated successfully"
            })
        else:
            return jsonify({"statusCode": 400, "message": "Failed to update workspace"}), 400
            
    except Exception as e:
        Log.error(f"[RAG-API] Update workspace failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces/<workspace_id>', methods=['DELETE'])
@require_auth
def delete_workspace(workspace_id):
    try:
        # 1. Verify workspace exists and belongs to user or admin
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not workspace:
            return jsonify({"statusCode": 404, "message": "Workspace not found"}), 404
            
        if not _can_access_workspace(workspace):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        # 2. Delete vectors from Qdrant
        try:
            qdrant_service.delete_by_workspace(workspace_id)
            Log.info(f"[RAG-API] Deleted vectors for workspace: {workspace_id}")
        except Exception as q_err:
            Log.error(f"[RAG-API] Failed to delete vectors from Qdrant: {q_err}")
            # We continue even if Qdrant fails to ensure DB consistency if possible
            
        # 3. Delete chat history from MongoDB
        try:
            chat_history_repo.clear_history(workspace_id)
            Log.info(f"[RAG-API] Deleted chat history for workspace: {workspace_id}")
        except Exception as h_err:
            Log.error(f"[RAG-API] Failed to delete chat history: {h_err}")

        # 4. Delete document records from MongoDB
        try:
            documents_repo.collection.delete_many({"workspace_id": workspace_id})
            Log.info(f"[RAG-API] Deleted document records for workspace: {workspace_id}")
        except Exception as d_err:
            Log.error(f"[RAG-API] Failed to delete document records: {d_err}")

        # 5. Delete workspace metadata from MongoDB
        success = workspaces_repo.delete_workspace(workspace_id)
        
        if success:
            return jsonify({
                "statusCode": 200,
                "message": "Workspace and all associated data deleted successfully"
            })
        else:
            return jsonify({"statusCode": 400, "message": "Failed to delete workspace metadata"}), 400
            
    except Exception as e:
        Log.error(f"[RAG-API] Delete workspace failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces/clear-all', methods=['DELETE'])
@require_auth
def delete_all_workspaces():
    try:
        # 1. Get all workspaces for this user
        workspaces = workspaces_repo.find_by_user(g.user_id)
        workspace_ids = [w["_id"] for w in workspaces]
        
        Log.info(f"[RAG-API] Clearing all data for user {g.user_id}. Workspaces found: {len(workspace_ids)}")

        # 2. Delete vectors from Qdrant for each workspace
        deleted_vectors_count = 0
        for ws_id in workspace_ids:
            try:
                qdrant_service.delete_by_workspace(ws_id)
                deleted_vectors_count += 1
            except Exception as q_err:
                Log.error(f"[RAG-API] Failed to delete vectors for workspace {ws_id}: {q_err}")

        # 3. Delete chat histories for all workspaces of this user
        try:
            deleted_history_count = chat_history_repo.delete_by_user(g.user_id)
            Log.info(f"[RAG-API] Deleted {deleted_history_count} chat history records")
        except Exception as h_err:
            Log.error(f"[RAG-API] Failed to delete chat history: {h_err}")

        # 4. Delete extraction logs
        try:
            deleted_logs_count = extraction_logs_repo.delete_by_user(g.user_id)
            Log.info(f"[RAG-API] Deleted {deleted_logs_count} extraction logs")
        except Exception as l_err:
            Log.error(f"[RAG-API] Failed to delete extraction logs: {l_err}")

        # 5. Delete documents metadata
        try:
            deleted_docs_count = documents_repo.delete_by_user(g.user_id)
            Log.info(f"[RAG-API] Deleted {deleted_docs_count} document records")
        except Exception as d_err:
            Log.error(f"[RAG-API] Failed to delete documents: {d_err}")

        # 6. Delete all workspaces from MongoDB
        try:
            deleted_workspaces_count = workspaces_repo.delete_by_user(g.user_id)
            Log.info(f"[RAG-API] Deleted {deleted_workspaces_count} workspace records")
        except Exception as w_err:
            Log.error(f"[RAG-API] Failed to delete workspaces: {w_err}")

        return jsonify({
            "statusCode": 200,
            "message": "All workspaces and associated data cleared successfully",
            "data": {
                "workspaces_deleted": len(workspace_ids),
                "history_cleared": True,
                "logs_cleared": True,
                "documents_cleared": True
            }
        })
    except Exception as e:
        Log.error(f"[RAG-API] Clear all failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces/<workspace_id>/upload', methods=['POST'])
@require_auth
def upload_to_workspace(workspace_id):
    try:
        # 1. Verify workspace
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not _can_access_workspace(workspace):
            return jsonify({"statusCode": 403, "message": "Access denied to workspace"}), 403

        is_allowed, msg = subscription_service.check_quota(g.user)
        if not is_allowed:
            return jsonify({"statusCode": 403, "message": f"Quota exceeded: {msg}"}), 403
            
        # 2. Get files and flags
        files = request.files.getlist('files')
        # Chỉ sử dụng vision_extract khi truyền cờ 'vision' bằng True (mặc định ưu tiên deepdoc và viet ocr)
        vision_extract = request.args.get('vision', 'false').lower() == 'true' or request.form.get('vision', 'false').lower() == 'true'
        category = request.form.get('category') or request.args.get('category')
        if category:
            category = category.strip()
            # Validate category exists and is active in this workspace
            cat_obj = category_repo.find_active_by_slug(workspace_id, category)
            if not cat_obj:
                return jsonify({"statusCode": 400, "message": f"Category '{category}' không tồn tại trong workspace"}), 400
        else:
            category = None

        if not files:
            return jsonify({"statusCode": 400, "message": "No files uploaded"}), 400
            
        if len(files) > MAX_FILE_COUNT:
            return jsonify({"statusCode": 400, "message": f"Tối đa {MAX_FILE_COUNT} file mỗi lần upload"}), 400

        # 3. Check individual file size
        for file in files:
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)
            
            if file_size > MAX_RAG_FILE_SIZE:
                 return jsonify({
                     "statusCode": 413, 
                     "message": f"File '{file.filename}' quá lớn. Giới hạn {MAX_RAG_FILE_SIZE/1024/1024}MB"
                 }), 413

        # Check document limit
        current_docs_count = documents_repo.count_by_workspace(workspace_id)
        if current_docs_count >= MAX_DOCUMENTS_PER_WORKSPACE:
             return jsonify({"statusCode": 400, "message": f"Workspace đã đạt giới hạn {MAX_DOCUMENTS_PER_WORKSPACE} tài liệu"}), 400

        from src.shared.utils.file_utils import save_uploaded_file_list
        saved_paths = save_uploaded_file_list(files)
        
        if not saved_paths:
             return jsonify({"statusCode": 400, "message": "No valid files saved"}), 400

        enqueued_docs = []

        # 3. Save to DB and Enqueue Task
        for idx, file_path in enumerate(saved_paths):
            original_filename = files[idx].filename
            
            # Save Initial Doc record
            doc_id = documents_repo.save_document(
                user_id=g.user_id,
                workspace_id=workspace_id,
                filename=original_filename,
                status=DocStatus.UPLOADED,
                category=category,
                source_files=[
                    {
                        "file_name": os.path.basename(file_path),
                        "storage_path": file_path.replace("\\", "/")
                    }
                ]
            )
            
            from src.shared.utils.redis_client import publish_event
            publish_event(g.user_id, "document_status", {
                "document_id": doc_id,
                "status": DocStatus.UPLOADED,
                "filename": original_filename,
                "workspace_id": workspace_id,
                "category": category,
                "message": "Document uploaded and enqueued"
            })

            rag_queue.enqueue(
                process_document_task,
                args=(doc_id, workspace_id, file_path, original_filename, g.user_id),
                kwargs={"vision_extract": vision_extract, "category": category},
                job_timeout='30m' 
            )
            
            enqueued_docs.append({
                "document_id": doc_id,
                "filename": original_filename,
                "category": category,
                "status": DocStatus.UPLOADED
            })
            
            Log.info(f"[RAG-API] Enqueued document {original_filename} (ID: {doc_id}, Category: {category})")

        return jsonify({
            "statusCode": 202, # Accepted
            "message": f"Successfully enqueued {len(enqueued_docs)} documents for processing",
            "data": {
                "documents": enqueued_docs
            }
        }), 202
        
    except Exception as e:
        Log.error(f"[RAG-API] Multi-upload failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces/<workspace_id>/documents', methods=['GET'])
@require_auth
def list_documents(workspace_id):
    try:
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not _can_access_workspace(workspace):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403
            
        category = request.args.get('category')
        documents = documents_repo.find_by_workspace(workspace_id, category=category)
        
        # Populate category details (name, icon)
        categories = category_repo.list_by_workspace(workspace_id, include_deleted=True)
        cat_map = {c["slug"]: c for c in categories}

        # Convert ObjectId to string and enrich category info
        for doc in documents:
            doc["_id"] = str(doc["_id"])
            if "user_id" in doc: doc["user_id"] = str(doc["user_id"])
            doc_cat = doc.get("category")
            if doc_cat and doc_cat in cat_map:
                c_info = cat_map[doc_cat]
                doc["category_name"] = c_info.get("name")
                doc["category_icon"] = c_info.get("icon")
            else:
                doc["category_name"] = None
                doc["category_icon"] = None
            
        return jsonify({
            "statusCode": 200,
            "data": list(documents)
        })
    except Exception as e:
        Log.error(f"[RAG-API] List documents failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/documents/<document_id>/status', methods=['GET'])
@require_auth
def get_document_status(document_id):
    try:
        doc = documents_repo.find_by_id(document_id)
        if not doc:
            return jsonify({"statusCode": 404, "message": "Document not found"}), 404
            
        if not _can_access_document(doc):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403
            
        return jsonify({
            "statusCode": 200,
            "data": {
                "document_id": str(doc["_id"]),
                "filename": doc["filename"],
                "status": doc["status"],
                "total_chunks": doc.get("total_chunks", 0),
                "result": doc.get("result"), # Extracted JSON data for detect pipes
                "debug": doc.get("debug"),
                "error": doc.get("error_message"),
                "updated_at": doc.get("updated_at")
            }
        })
    except Exception as e:
        Log.error(f"[RAG-API] Get status failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces/<workspace_id>/chat', methods=['POST'])
@require_auth
def chat_with_workspace(workspace_id):
    try:
        # Verify workspace
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not _can_access_workspace(workspace):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        data = request.json or {}
        question = data.get('question')
        provider = data.get('provider', 'auto')
        category = data.get('category')
        
        if not question:
            return jsonify({"statusCode": 400, "message": "Question is required"}), 400
            
        # Check quota
        is_allowed, msg = subscription_service.check_quota(g.user)
        if not is_allowed:
            return jsonify({"statusCode": 403, "message": msg}), 403

        # Increment usage
        if g.user.get('account_id'):
            accounts_repo.increment_usage(g.user.get('account_id'))

        result = rag_service.query(question, workspace_id, provider=provider, category=category)
        
        # Save to History
        chat_history_repo.save_message(
            workspace_id=workspace_id,
            user_id=g.user_id,
            question=question,
            answer=result["answer"],
            sources=result["sources"],
            provider=result["provider"]
        )
        
        return jsonify({
            "statusCode": 200,
            "data": result
        })
    except Exception as e:
        Log.error(f"[RAG-API] Chat failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces/<workspace_id>/suggest', methods=['GET'])
@require_auth
def suggest_workspace_questions(workspace_id):
    try:
        # Verify workspace
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not _can_access_workspace(workspace):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        category = request.args.get('category')
        suggestions = rag_service.suggest_questions(workspace_id, category=category)
        
        return jsonify({
            "statusCode": 200,
            "data": {"suggestions": suggestions}
        })
    except Exception as e:
        Log.error(f"[RAG-API] Suggestions failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces/<workspace_id>/history', methods=['GET'])
@require_auth
def get_workspace_chat_history(workspace_id):
    try:
        # Verify workspace
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not _can_access_workspace(workspace):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        limit = request.args.get('limit', default=50, type=int)
        history = chat_history_repo.get_history(workspace_id, limit=limit)
        
        return jsonify({
            "statusCode": 200,
            "data": {
                "workspace_id": workspace_id,
                "history": history
            }
        })
    except Exception as e:
        Log.error(f"[RAG-API] Get history failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@rag_bp.route('/api/rag/workspaces/<workspace_id>/history', methods=['DELETE'])
@require_auth
def delete_workspace_chat_history(workspace_id):
    try:
        # Verify workspace
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not _can_access_workspace(workspace):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        deleted_count = chat_history_repo.clear_history(workspace_id)
        
        return jsonify({
            "statusCode": 200,
            "message": f"Successfully deleted {deleted_count} messages",
            "data": {"workspace_id": workspace_id}
        })
    except Exception as e:
        Log.error(f"[RAG-API] Delete history failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2 – Document Management
# ══════════════════════════════════════════════════════════════════════════════

# ── DELETE /api/rag/workspaces/<workspace_id>/documents/<document_id> ─────────
@rag_bp.route('/api/rag/workspaces/<workspace_id>/documents/<document_id>', methods=['DELETE'])
@require_auth
def delete_document(workspace_id, document_id):
    """
    Xóa một document riêng lẻ trong workspace:
      1. Verify quyền sở hữu workspace + document
      2. Xóa tất cả vector trong Qdrant (theo workspace_id + document_name)
      3. Xóa document record trong MongoDB
    """
    try:
        # 1. Verify workspace ownership
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not _can_access_workspace(workspace):
            return jsonify({"statusCode": 403, "message": "Access denied to workspace"}), 403

        # 2. Verify document belongs to this workspace and user
        doc = documents_repo.find_by_id(document_id)
        if not doc:
            return jsonify({"statusCode": 404, "message": "Document không tồn tại"}), 404

        if str(doc.get("workspace_id")) != workspace_id:
            return jsonify({"statusCode": 403, "message": "Document không thuộc workspace này"}), 403

        if not _can_access_document(doc):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        document_name = doc.get("filename", "")

        # 3. Xóa vectors trong Qdrant
        try:
            qdrant_service.delete_by_document(workspace_id, document_name)
            Log.info(f"[RAG-API] Đã xóa vectors Qdrant cho document: {document_name}")
        except Exception as q_err:
            Log.error(f"[RAG-API] Lỗi xóa Qdrant vectors: {q_err}")

        # 4. Xóa document record trong MongoDB
        deleted = documents_repo.delete_document(document_id)
        if not deleted:
            return jsonify({"statusCode": 404, "message": "Document không tìm thấy để xóa"}), 404

        Log.info(f"[RAG-API] Đã xóa document {document_id} ({document_name}) khỏi workspace {workspace_id}")
        return jsonify({
            "statusCode": 200,
            "message": f"Đã xóa document '{document_name}' thành công",
            "data": {"document_id": document_id, "document_name": document_name}
        })

    except Exception as e:
        Log.error(f"[RAG-API] delete_document error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── POST /api/rag/documents/<document_id>/reindex ─────────────────────────────
@rag_bp.route('/api/rag/documents/<document_id>/reindex', methods=['POST'])
@require_auth
def reindex_document(document_id):
    """
    Reindex một document đã tồn tại:
      1. Verify quyền sở hữu
      2. Lấy raw_text từ MongoDB (ưu tiên) hoặc báo lỗi nếu không có
      3. Xóa vectors cũ trong Qdrant
      4. Index lại vào Qdrant
      5. Cập nhật status trong MongoDB
    """
    try:
        # 1. Verify document ownership
        doc = documents_repo.find_by_id(document_id)
        if not doc:
            return jsonify({"statusCode": 404, "message": "Document không tồn tại"}), 404

        if not _can_access_document(doc):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        workspace_id = doc.get("workspace_id")
        if not workspace_id:
            return jsonify({"statusCode": 400, "message": "Document không thuộc workspace nào"}), 400

        document_name = doc.get("filename", "")
        raw_text = doc.get("raw_text", "")

        if not raw_text or not raw_text.strip():
            return jsonify({
                "statusCode": 400,
                "message": "Không có nội dung raw_text để reindex. "
                           "Document có thể chưa được trích xuất hoặc file gốc không còn khả dụng."
            }), 400

        # 2. Đánh trạng thái processing
        documents_repo.update_status(document_id, "processing")

        # 3. Xóa vectors cũ trong Qdrant
        try:
            qdrant_service.delete_by_document(workspace_id, document_name, document_id=str(document_id))
            Log.info(f"[RAG-API] Đã xóa vectors cũ: workspace={workspace_id}, doc={document_name}")
        except Exception as q_err:
            Log.error(f"[RAG-API] Lỗi xóa Qdrant vectors khi reindex: {q_err}")

        # 4. Index lại từ raw_text đã lưu
        structured_data = [{"text": raw_text, "page_num": 1}]
        doc_category = doc.get("category")
        total_chunks = rag_service.index_text(
            structured_data,
            workspace_id,
            document_name,
            category=doc_category,
            document_id=str(document_id)
        )

        # 5. Cập nhật status READY
        documents_repo.update_status(document_id, "ready", total_chunks=total_chunks)

        from src.shared.utils.redis_client import publish_event
        publish_event(g.user_id, "document_status", {
            "document_id": document_id,
            "status": "ready",
            "message": "Reindex hoàn tất"
        })

        Log.info(f"[RAG-API] Reindex thành công: doc={document_id}, chunks={total_chunks}")
        return jsonify({
            "statusCode": 200,
            "message": f"Reindex thành công '{document_name}'",
            "data": {
                "document_id": document_id,
                "document_name": document_name,
                "total_chunks": total_chunks,
                "category": doc_category
            }
        })

    except Exception as e:
        Log.error(f"[RAG-API] reindex_document error: {e}")
        try:
            documents_repo.update_status(document_id, "failed", error_message=str(e))
        except Exception:
            pass
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3 – Raw Text Support
# ══════════════════════════════════════════════════════════════════════════════

# ── POST /api/rag/workspaces/<workspace_id>/upload-text ───────────────────────
@rag_bp.route('/api/rag/workspaces/<workspace_id>/upload-text', methods=['POST'])
@require_auth
def upload_text_to_workspace(workspace_id):
    """
    Tạo document từ raw text (không cần file):
      Body JSON: { "text": "...", "document_name": "...", "category": "..." }
    """
    try:
        from src.core.config import DocStatus

        # 1. Verify workspace ownership
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not _can_access_workspace(workspace):
            return jsonify({"statusCode": 403, "message": "Access denied to workspace"}), 403

        # 2. Parse body
        data = request.get_json(silent=True) or {}
        text = (data.get("text") or "").strip()
        document_name = (data.get("document_name") or "").strip()
        category = data.get("category")
        if category:
            category = category.strip()
            cat_obj = category_repo.find_active_by_slug(workspace_id, category)
            if not cat_obj:
                return jsonify({"statusCode": 400, "message": f"Category '{category}' không tồn tại trong workspace"}), 400
        else:
            category = None

        if not text:
            return jsonify({"statusCode": 400, "message": "Trường 'text' là bắt buộc"}), 400
        
        if not document_name:
            from src.modules.rag.llm_service import llm_service
            document_name = llm_service.generate_title(text, fallback_filename="Văn bản mới")

        # Check document limit
        current_docs_count = documents_repo.count_by_workspace(workspace_id)
        if current_docs_count >= MAX_DOCUMENTS_PER_WORKSPACE:
            return jsonify({
                "statusCode": 400,
                "message": f"Workspace đã đạt giới hạn {MAX_DOCUMENTS_PER_WORKSPACE} tài liệu"
            }), 400

        # 3. Lưu document vào MongoDB với raw_text
        doc_id = documents_repo.save_document(
            user_id=g.user_id,
            workspace_id=workspace_id,
            filename=document_name,
            status=DocStatus.PROCESSING,
            raw_text=text,
            category=category
        )

        # 4. Index vào Qdrant ngay lập tức
        structured_data = [{"text": text, "page_num": 1}]
        total_chunks = rag_service.index_text(
            structured_data,
            workspace_id,
            document_name,
            category=category,
            document_id=str(doc_id)
        )

        # 5. Cập nhật status READY
        documents_repo.update_status(doc_id, DocStatus.READY, total_chunks=total_chunks)

        from src.shared.utils.redis_client import publish_event
        publish_event(g.user_id, "document_status", {
            "document_id": doc_id,
            "status": DocStatus.READY,
            "filename": document_name,
            "workspace_id": workspace_id,
            "category": category
        })

        Log.info(f"[RAG-API] Upload text thành công: doc={doc_id}, name={document_name}, category={category}, chunks={total_chunks}")
        return jsonify({
            "statusCode": 201,
            "message": f"Đã tạo và index document '{document_name}' từ raw text thành công",
            "data": {
                "document_id": doc_id,
                "document_name": document_name,
                "category": category,
                "total_chunks": total_chunks,
                "status": DocStatus.READY
            }
        }), 201

    except Exception as e:
        Log.error(f"[RAG-API] upload_text error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── GET /api/rag/documents/<document_id>/text (hoặc /content) ────────────────
@rag_bp.route('/api/rag/documents/<document_id>/text', methods=['GET'])
@rag_bp.route('/api/rag/documents/<document_id>/content', methods=['GET'])
@require_auth
def get_document_content(document_id):
    """
    Lấy toàn bộ nội dung văn bản (raw_text) đã được OCR của tài liệu để debug hoặc xem trước.
    """
    try:
        doc = documents_repo.find_by_id(document_id)
        if not doc or not _can_access_document(doc):
            return jsonify({"statusCode": 404, "message": "Không tìm thấy tài liệu hoặc không có quyền truy cập"}), 404

        raw_text = doc.get("raw_text") or ""
        
        return jsonify({
            "statusCode": 200,
            "data": {
                "document_id": str(doc["_id"]),
                "filename": doc.get("filename"),
                "original_filename": doc.get("original_filename"),
                "workspace_id": str(doc.get("workspace_id")),
                "category": doc.get("category"),
                "status": doc.get("status"),
                "total_chunks": doc.get("total_chunks", 0),
                "total_characters": len(raw_text),
                "total_words": len(raw_text.split()) if raw_text else 0,
                "raw_text": raw_text,
                "source_files": doc.get("source_files", []),
                "created_at": doc.get("created_at"),
                "updated_at": doc.get("updated_at")
            }
        }), 200

    except Exception as e:
        Log.error(f"[RAG-API] get_document_content error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── GET /api/rag/documents/<document_id>/chunks ──────────────────────────────
@rag_bp.route('/api/rag/documents/<document_id>/chunks', methods=['GET'])
@require_auth
def get_document_chunks(document_id):
    """
    Lấy danh sách các chunk thực tế trong Qdrant của document để debug:
    Xem phân bổ chunk, tiêu đề đề mục (section_title), số trang, nội dung từng chunk.
    """
    try:
        doc = documents_repo.find_by_id(document_id)
        if not doc or not _can_access_document(doc):
            return jsonify({"statusCode": 404, "message": "Không tìm thấy tài liệu hoặc không có quyền truy cập"}), 404

        workspace_id = str(doc.get("workspace_id"))
        doc_name = doc.get("filename") or doc.get("original_filename")

        from qdrant_client.http import models
        filter_conditions = [
            models.FieldCondition(key="workspace_id", match=models.MatchValue(value=workspace_id))
        ]
        filter_conditions.append(
            models.FieldCondition(key="document_id", match=models.MatchValue(value=str(document_id)))
        )

        scroll_res = qdrant_service.scroll(
            scroll_filter=models.Filter(must=filter_conditions),
            limit=500
        )
        points = scroll_res[0] if scroll_res else []

        # Fallback theo document_name nếu tài liệu cũ chưa có document_id trong payload
        if not points and doc_name:
            scroll_res = qdrant_service.scroll(
                scroll_filter=models.Filter(must=[
                    models.FieldCondition(key="workspace_id", match=models.MatchValue(value=workspace_id)),
                    models.FieldCondition(key="document_name", match=models.MatchValue(value=doc_name))
                ]),
                limit=500
            )
            points = scroll_res[0] if scroll_res else []

        chunks_list = []
        for p in points:
            payload = p.payload or {}
            chunks_list.append({
                "chunk_id": str(p.id),
                "chunk_index": payload.get("chunk_index", 0),
                "page_num": payload.get("page_num", 1),
                "section_title": payload.get("section_title"),
                "chapter_title": payload.get("chapter_title"),
                "category": payload.get("category"),
                "text": payload.get("text", ""),
                "char_count": len(payload.get("text", ""))
            })

        chunks_list.sort(key=lambda x: x["chunk_index"])

        return jsonify({
            "statusCode": 200,
            "data": {
                "document_id": document_id,
                "document_name": doc_name,
                "category": doc.get("category"),
                "total_chunks": len(chunks_list),
                "chunks": chunks_list
            }
        }), 200

    except Exception as e:
        Log.error(f"[RAG-API] get_document_chunks error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── PUT /api/rag/documents/<document_id>/text ─────────────────────────────────
@rag_bp.route('/api/rag/documents/<document_id>/text', methods=['PUT'])
@require_auth
def update_document_text(document_id):
    """
    Cập nhật raw_text của document và reindex tự động:
      Body JSON: { "new_text": "...", "category": "..." }
    """
    try:
        from src.core.config import DocStatus

        # 1. Verify document ownership
        doc = documents_repo.find_by_id(document_id)
        if not doc:
            return jsonify({"statusCode": 404, "message": "Document không tồn tại"}), 404

        if not _can_access_document(doc):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        # 2. Parse body
        data = request.get_json(silent=True) or {}
        new_text = (data.get("new_text") or "").strip()

        if not new_text:
            return jsonify({"statusCode": 400, "message": "Trường 'new_text' là bắt buộc"}), 400

        workspace_id = doc.get("workspace_id")
        document_name = doc.get("filename", "")

        if not workspace_id:
            return jsonify({"statusCode": 400, "message": "Document không thuộc workspace nào"}), 400

        category = doc.get("category")
        if "category" in data:
            req_cat = data.get("category")
            if req_cat:
                req_cat = req_cat.strip()
                cat_obj = category_repo.find_active_by_slug(workspace_id, req_cat)
                if not cat_obj:
                    return jsonify({"statusCode": 400, "message": f"Category '{req_cat}' không tồn tại trong workspace"}), 400
                category = req_cat
            else:
                category = None
            documents_repo.update_metadata(document_id, category=category)

        # 3. Đánh trạng thái processing
        documents_repo.update_status(document_id, DocStatus.PROCESSING)

        # 4. Cập nhật raw_text trong MongoDB
        documents_repo.update_raw_text(document_id, new_text)

        # 5. Xóa vectors cũ
        try:
            qdrant_service.delete_by_document(workspace_id, document_name, document_id=str(document_id))
            Log.info(f"[RAG-API] Đã xóa vectors cũ khi update text: doc={document_name}")
        except Exception as q_err:
            Log.error(f"[RAG-API] Lỗi xóa Qdrant khi update text: {q_err}")

        # 6. Index lại với nội dung mới
        structured_data = [{"text": new_text, "page_num": 1}]
        total_chunks = rag_service.index_text(
            structured_data,
            workspace_id,
            document_name,
            category=category,
            document_id=str(document_id)
        )

        # 7. Cập nhật status READY
        documents_repo.update_status(document_id, DocStatus.READY, total_chunks=total_chunks)

        from src.shared.utils.redis_client import publish_event
        publish_event(g.user_id, "document_status", {
            "document_id": document_id,
            "status": DocStatus.READY,
            "message": "Cập nhật nội dung và reindex thành công"
        })

        Log.info(f"[RAG-API] Update text + reindex thành công: doc={document_id}, chunks={total_chunks}")
        return jsonify({
            "statusCode": 200,
            "message": f"Đã cập nhật nội dung và reindex '{document_name}' thành công",
            "data": {
                "document_id": document_id,
                "document_name": document_name,
                "category": category,
                "total_chunks": total_chunks
            }
        })

    except Exception as e:
        Log.error(f"[RAG-API] update_document_text error: {e}")
        try:
            documents_repo.update_status(document_id, "failed", error_message=str(e))
        except Exception:
            pass
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 4 – Advanced Features
# ══════════════════════════════════════════════════════════════════════════════

# ── PUT /api/rag/workspaces/<workspace_id>/documents/<document_id>/replace ────
@rag_bp.route('/api/rag/workspaces/<workspace_id>/documents/<document_id>/replace', methods=['PUT'])
@require_auth
def replace_document_file(workspace_id, document_id):
    """
    Thay thế file của document bằng file mới:
      Form-data: file (required)
      1. Verify quyền sở hữu workspace + document
      2. Lưu file mới vào disk
      3. Xóa vectors cũ trong Qdrant
      4. Cập nhật MongoDB (filename mới, status=uploaded, xóa raw_text cũ)
      5. Enqueue process_document_task để xử lý bất đồng bộ
    """
    try:
        from src.core.config import DocStatus
        from src.shared.utils.file_utils import save_uploaded_file_list

        # 1. Verify workspace ownership
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not _can_access_workspace(workspace):
            return jsonify({"statusCode": 403, "message": "Access denied to workspace"}), 403

        # 2. Verify document
        doc = documents_repo.find_by_id(document_id)
        if not doc:
            return jsonify({"statusCode": 404, "message": "Document không tồn tại"}), 404

        if str(doc.get("workspace_id")) != workspace_id:
            return jsonify({"statusCode": 403, "message": "Document không thuộc workspace này"}), 403

        if not _can_access_document(doc):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        # 3. Lấy file mới
        new_file = request.files.get("file")
        if not new_file:
            return jsonify({"statusCode": 400, "message": "Trường 'file' là bắt buộc"}), 400

        # Check file size
        new_file.seek(0, os.SEEK_END)
        file_size = new_file.tell()
        new_file.seek(0)
        if file_size > MAX_RAG_FILE_SIZE:
            return jsonify({
                "statusCode": 413,
                "message": f"File quá lớn. Giới hạn {MAX_RAG_FILE_SIZE / 1024 / 1024:.0f}MB"
            }), 413

        # 4. Lưu file mới vào disk
        # 4. Lưu file mới vào disk
        saved_paths = save_uploaded_file_list([new_file])
        if not saved_paths:
            return jsonify({"statusCode": 400, "message": "Không thể lưu file"}), 400

        new_file_path = saved_paths[0]
        original_filename = new_file.filename
        old_document_name = doc.get("filename", "")

        # Category from request or keep existing
        category = doc.get("category")
        if "category" in request.form or "category" in request.args:
            req_cat = request.form.get("category") or request.args.get("category")
            if req_cat:
                req_cat = req_cat.strip()
                cat_obj = category_repo.find_active_by_slug(workspace_id, req_cat)
                if not cat_obj:
                    return jsonify({"statusCode": 400, "message": f"Category '{req_cat}' không tồn tại trong workspace"}), 400
                category = req_cat
            else:
                category = None

        # 5. Xóa vectors cũ
        try:
            qdrant_service.delete_by_document(workspace_id, old_document_name, document_id=str(document_id))
            Log.info(f"[RAG-API] Đã xóa vectors cũ khi replace: {old_document_name}")
        except Exception as q_err:
            Log.error(f"[RAG-API] Lỗi xóa Qdrant khi replace: {q_err}")

        # 6. Cập nhật MongoDB (filename mới, xóa raw_text cũ, status=uploaded)
        documents_repo.collection.update_one(
            {"_id": __import__("bson").ObjectId(document_id)},
            {"$set": {
                "filename": original_filename,
                "status": DocStatus.UPLOADED,
                "category": category,
                "raw_text": None,
                "total_chunks": 0,
                "error_message": None,
                "updated_at": __import__("datetime").datetime.now(),
                "source_files": [{
                    "file_name": os.path.basename(new_file_path),
                    "storage_path": new_file_path.replace("\\", "/")
                }]
            }}
        )

        # 7. Enqueue process_document_task
        vision_extract = request.args.get('vision', 'false').lower() == 'true' or request.form.get('vision', 'false').lower() == 'true'
        rag_queue.enqueue(
            process_document_task,
            args=(document_id, workspace_id, new_file_path, original_filename, g.user_id),
            kwargs={"vision_extract": vision_extract, "category": category},
            job_timeout='30m'
        )

        from src.shared.utils.redis_client import publish_event
        publish_event(g.user_id, "document_status", {
            "document_id": document_id,
            "status": DocStatus.UPLOADED,
            "filename": original_filename,
            "category": category,
            "message": "File mới đã được upload và đang xử lý"
        })

        Log.info(f"[RAG-API] Replace file thành công: doc={document_id}, new_file={original_filename}")
        return jsonify({
            "statusCode": 202,
            "message": f"Đã thay thế file bằng '{original_filename}', đang xử lý...",
            "data": {
                "document_id": document_id,
                "new_filename": original_filename,
                "category": category,
                "status": DocStatus.UPLOADED
            }
        }), 202

    except Exception as e:
        Log.error(f"[RAG-API] replace_document_file error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── POST /api/rag/workspaces/<workspace_id>/reindex-all ───────────────────────
@rag_bp.route('/api/rag/workspaces/<workspace_id>/reindex-all', methods=['POST'])
@require_auth
def reindex_all_documents(workspace_id):
    """
    Reindex toàn bộ document trong workspace (bỏ qua tài liệu is_deleted).
    """
    try:
        from src.core.config import DocStatus

        # 1. Verify workspace ownership
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not _can_access_workspace(workspace):
            return jsonify({"statusCode": 403, "message": "Access denied to workspace"}), 403

        # 2. Lấy tất cả documents active trong workspace
        all_docs = list(documents_repo.find_by_workspace(workspace_id, include_deleted=False))
        if not all_docs:
            return jsonify({
                "statusCode": 200,
                "message": "Workspace không có document nào để reindex",
                "data": {"total": 0, "succeeded": 0, "skipped": 0, "failed": 0}
            })

        succeeded, skipped, failed = 0, 0, 0
        results = []

        for doc in all_docs:
            doc_id = str(doc["_id"])
            document_name = doc.get("filename", "")
            raw_text = doc.get("raw_text", "")
            doc_category = doc.get("category")

            if not raw_text or not raw_text.strip():
                Log.info(f"[RAG-API] reindex-all: Bỏ qua {document_name} (không có raw_text)")
                skipped += 1
                results.append({"document_id": doc_id, "name": document_name, "result": "skipped",
                                 "reason": "Không có raw_text"})
                continue

            try:
                # Xóa vectors cũ
                qdrant_service.delete_by_document(workspace_id, document_name, document_id=doc_id)

                # Index lại
                structured_data = [{"text": raw_text, "page_num": 1}]
                total_chunks = rag_service.index_text(
                    structured_data,
                    workspace_id,
                    document_name,
                    category=doc_category,
                    document_id=doc_id
                )

                # Cập nhật status
                documents_repo.update_status(doc_id, DocStatus.READY, total_chunks=total_chunks)

                succeeded += 1
                results.append({"document_id": doc_id, "name": document_name,
                                 "category": doc_category, "result": "success", "total_chunks": total_chunks})
                Log.info(f"[RAG-API] reindex-all: Thành công {document_name} ({total_chunks} chunks)")

            except Exception as doc_err:
                failed += 1
                results.append({"document_id": doc_id, "name": document_name,
                                 "result": "failed", "error": str(doc_err)})
                Log.error(f"[RAG-API] reindex-all: Lỗi reindex {document_name}: {doc_err}")
                try:
                    documents_repo.update_status(doc_id, DocStatus.FAILED, error_message=str(doc_err))
                except Exception:
                    pass

        Log.info(f"[RAG-API] reindex-all hoàn tất: workspace={workspace_id}, "
                 f"thành công={succeeded}, bỏ qua={skipped}, lỗi={failed}")

        return jsonify({
            "statusCode": 200,
            "message": f"Reindex hoàn tất: {succeeded} thành công, {skipped} bỏ qua, {failed} lỗi",
            "data": {
                "total": len(all_docs),
                "succeeded": succeeded,
                "skipped": skipped,
                "failed": failed,
                "results": results
            }
        })

    except Exception as e:
        Log.error(f"[RAG-API] reindex_all error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── PUT /api/rag/documents/<document_id> ─────────────────────────────────────
@rag_bp.route('/api/rag/documents/<document_id>', methods=['PUT'])
@require_auth
def update_document_metadata(document_id):
    """
    Cập nhật metadata của document (filename, description, tags, category).
    Nếu đổi category, gọi Qdrant set_document_category payload mà không re-embed.
    """
    try:
        # 1. Verify document ownership
        doc = documents_repo.find_by_id(document_id)
        if not doc:
            return jsonify({"statusCode": 404, "message": "Document không tồn tại"}), 404

        if not _can_access_document(doc):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        workspace_id = doc.get("workspace_id")
        data = request.get_json(silent=True) or {}

        ALLOWED_FIELDS = {"filename", "description", "tags", "category"}
        update_fields = {k: v for k, v in data.items() if k in ALLOWED_FIELDS}

        if not update_fields:
            return jsonify({
                "statusCode": 400,
                "message": f"Không có trường hợp lệ. Cho phép: {', '.join(ALLOWED_FIELDS)}"
            }), 400

        # Validate tags
        if "tags" in update_fields:
            if not isinstance(update_fields["tags"], list):
                return jsonify({"statusCode": 400, "message": "'tags' phải là danh sách"}), 400

        # Validate & handle category change
        if "category" in update_fields:
            new_cat = update_fields["category"]
            if new_cat:
                new_cat = str(new_cat).strip()
                cat_obj = category_repo.find_active_by_slug(workspace_id, new_cat)
                if not cat_obj:
                    return jsonify({"statusCode": 400, "message": f"Category '{new_cat}' không tồn tại trong workspace"}), 400
                update_fields["category"] = new_cat
            else:
                update_fields["category"] = None

            # Update Qdrant payload directly
            try:
                qdrant_service.set_document_category(
                    workspace_id=workspace_id,
                    document_id=str(document_id),
                    document_name=doc.get("filename", ""),
                    category=update_fields["category"]
                )
            except Exception as q_err:
                Log.error(f"[RAG-API] Failed to update category in Qdrant: {q_err}")

            # Audit log
            audit_log_repo.log(
                action="document.category_change",
                actor_user_id=g.user_id,
                workspace_id=workspace_id,
                target_type="document",
                target_id=str(document_id),
                snapshot={"old_category": doc.get("category"), "new_category": update_fields["category"], "filename": doc.get("filename")},
                ip=request.remote_addr,
                user_agent=request.headers.get("User-Agent")
            )

        # 3. Cập nhật MongoDB
        updated = documents_repo.update_metadata(document_id, **update_fields)
        if not updated:
            return jsonify({"statusCode": 404, "message": "Document không tìm thấy để cập nhật"}), 404

        Log.info(f"[RAG-API] Cập nhật metadata thành công: doc={document_id}, fields={list(update_fields.keys())}")
        return jsonify({
            "statusCode": 200,
            "message": "Cập nhật metadata thành công",
            "data": {
                "document_id": document_id,
                "updated_fields": list(update_fields.keys()),
                "values": update_fields
            }
        })

    except Exception as e:
        Log.error(f"[RAG-API] update_document_metadata error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@rag_bp.route('/api/rag/playground/search', methods=['POST'])
@require_auth
def playground_search():
    """
    RAG Playground / Test Search API for Admin & Developers.
    Accepts a question, performs vector retrieval, returns similarity scores of all chunks,
    full context, and LLM answer with has_answer analysis.
    """
    try:
        data = request.json or {}
        workspace_id = data.get('workspace_id')
        question = data.get('query') or data.get('question')

        if not workspace_id:
            return jsonify({"statusCode": 400, "message": "workspace_id là bắt buộc"}), 400
        if not question or not str(question).strip():
            return jsonify({"statusCode": 400, "message": "query hoặc question không được để trống"}), 400

        workspace = workspaces_repo.find_by_id(workspace_id)
        if not workspace or not _can_access_workspace(workspace):
            return jsonify({"statusCode": 403, "message": "Không có quyền truy cập workspace này"}), 403

        category = data.get('category')
        if category:
            category = str(category).strip()
            # If slug doesn't exist, allow or warn
            cat_obj = category_repo.find_active_by_slug(workspace_id, category)
            if not cat_obj:
                return jsonify({"statusCode": 404, "message": f"Category slug '{category}' không tồn tại trong workspace"}), 404

        limit = int(data.get('limit', 7))
        min_score = float(data.get('min_score', 0.35))
        domain = data.get('domain', 'administrative_doc')
        generate_answer = bool(data.get('generate_answer', True))
        provider = data.get('provider', 'auto')

        result = rag_service.inspect_search(
            question=str(question).strip(),
            workspace_id=str(workspace_id),
            category=category,
            limit=limit,
            min_score=min_score,
            domain=domain,
            generate_answer=generate_answer,
            provider=provider
        )

        return jsonify({
            "statusCode": 200,
            "message": "Tìm kiếm RAG Playground thành công",
            "data": result
        }), 200

    except Exception as e:
        Log.error(f"[RAG Playground API] Error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@rag_bp.route('/api/rag/documents/<document_id>/reindex', methods=['POST'])
@require_auth
def reindex_document_endpoint(document_id):
    """
    Reindex document using the smart structure-aware chunker.
    Uses stored raw_text from MongoDB, purges old Qdrant chunks, and re-embeds.
    """
    try:
        doc = documents_repo.find_by_id(document_id)
        if not doc or not _can_access_document(doc):
            return jsonify({"statusCode": 404, "message": "Không tìm thấy tài liệu hoặc không có quyền truy cập"}), 404

        workspace_id = str(doc.get("workspace_id"))
        doc_name = doc.get("filename") or doc.get("original_filename") or "document"
        category = doc.get("category")
        raw_text = doc.get("raw_text")

        if not raw_text:
            return jsonify({"statusCode": 400, "message": "Tài liệu chưa có raw_text để reindex"}), 400

        # Purge old points in Qdrant
        try:
            from qdrant_client.http import models
            qdrant_service.client.delete(
                collection_name=qdrant_service.collection_name,
                points_selector=models.FilterSelector(
                    filter=models.Filter(
                        must=[
                            models.FieldCondition(key="workspace_id", match=models.MatchValue(value=workspace_id)),
                            models.FieldCondition(key="document_id", match=models.MatchValue(value=str(document_id)))
                        ]
                    )
                )
            )
        except Exception as q_err:
            Log.warning(f"[RAG-API] Xóa chunk cũ khi reindex: {q_err}")

        # Index text with new smart chunker
        total_chunks = rag_service.index_text(
            data=raw_text,
            workspace_id=workspace_id,
            document_name=doc_name,
            category=category,
            document_id=str(document_id)
        )

        documents_repo.update_metadata(document_id, total_chunks=total_chunks)

        return jsonify({
            "statusCode": 200,
            "message": f"Reindex tài liệu thành công với cấu trúc thông minh!",
            "data": {
                "document_id": document_id,
                "total_chunks": total_chunks,
                "document_name": doc_name,
                "category": category
            }
        }), 200

    except Exception as e:
        Log.error(f"[RAG-API] reindex_document error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# =========================================================================
# DOCUMENT RECORDS SYNC APIS (VĂN BẢN ĐẾN DẠNG DÒNG DỮ LIỆU)
# =========================================================================

@rag_bp.route('/api/rag/records', methods=['POST'])
@require_auth
def create_document_record():
    """
    Tiếp nhận 1 dòng dữ liệu văn bản đến từ backend external.
    Thực hiện embed duy nhất chuỗi ngữ nghĩa của dòng này và lưu vào Qdrant (0% re-chunking).
    """
    try:
        data = request.json or {}
        workspace_id = data.get("workspace_id")
        if not workspace_id:
            return jsonify({"statusCode": 400, "message": "Trường 'workspace_id' là bắt buộc"}), 400

        record = data.get("record") or data
        doc_id = record.get("id") or record.get("document_id")
        if not doc_id:
            return jsonify({"statusCode": 400, "message": "Record phải có trường 'id' hoặc 'document_id'"}), 400

        rag_service.index_document_record(record=record, workspace_id=workspace_id)

        return jsonify({
            "statusCode": 201,
            "message": "Đã đồng bộ văn bản đến vào tri thức RAG thành công",
            "data": {
                "document_id": doc_id,
                "workspace_id": workspace_id,
                "arrivalNo": record.get("arrivalNo"),
                "documentNo": record.get("documentNo")
            }
        }), 201
    except Exception as e:
        Log.error(f"[RAG-API] create_document_record error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@rag_bp.route('/api/rag/records/<document_id>/metadata', methods=['PATCH'])
@require_auth
def patch_document_record_metadata(document_id):
    """
    Cập nhật metadata động (status, priority, security, assignees, deadline...)
    cho 1 dòng văn bản đến mà KHÔNG re-embed (0% tài nguyên embedding, tốc độ < 2ms).
    """
    try:
        data = request.json or {}
        workspace_id = data.get("workspace_id") or request.args.get("workspace_id")
        if not workspace_id:
            return jsonify({"statusCode": 400, "message": "Trường 'workspace_id' là bắt buộc"}), 400

        # Lọc bỏ các trường metadata nếu được bọc trong 'updates' hoặc lấy thẳng từ body
        updates = data.get("updates") if "updates" in data else data
        updates = {k: v for k, v in updates.items() if k not in ["workspace_id", "document_id", "id"]}

        if not updates:
            return jsonify({"statusCode": 400, "message": "Không có trường metadata nào được cung cấp để cập nhật"}), 400

        rag_service.patch_document_record_metadata(
            workspace_id=workspace_id,
            document_id=document_id,
            updates=updates
        )

        return jsonify({
            "statusCode": 200,
            "message": "Cập nhật metadata văn bản thành công (0% re-embedding)",
            "data": {
                "document_id": document_id,
                "workspace_id": workspace_id,
                "updated_fields": list(updates.keys())
            }
        }), 200
    except Exception as e:
        Log.error(f"[RAG-API] patch_document_record_metadata error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@rag_bp.route('/api/rag/records/<document_id>', methods=['DELETE'])
@require_auth
def delete_document_record(document_id):
    """
    Xóa dòng dữ liệu văn bản đến khỏi Vector DB khi văn bản bị hủy/xóa ở hệ thống chính.
    """
    try:
        workspace_id = request.args.get("workspace_id") or (request.json or {}).get("workspace_id")
        if not workspace_id:
            return jsonify({"statusCode": 400, "message": "Query param hoặc body 'workspace_id' là bắt buộc"}), 400

        rag_service.delete_document_record(workspace_id=workspace_id, document_id=document_id)

        return jsonify({
            "statusCode": 200,
            "message": f"Đã xóa dòng văn bản '{document_id}' khỏi tri thức RAG thành công",
            "data": {
                "document_id": document_id,
                "workspace_id": workspace_id
            }
        }), 200
    except Exception as e:
        Log.error(f"[RAG-API] delete_document_record error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@rag_bp.route('/api/rag/records/search', methods=['POST'])
@require_auth
def search_document_records():
    """
    Tìm kiếm thông minh kết hợp Exact Match Filter và Semantic Search cho văn bản đến.
    Hỗ trợ lọc theo số đến, số ký hiệu, trạng thái, độ khẩn, độ mật, người xử lý...
    """
    try:
        data = request.json or {}
        workspace_id = data.get("workspace_id")
        if not workspace_id:
            return jsonify({"statusCode": 400, "message": "Trường 'workspace_id' là bắt buộc"}), 400

        query = data.get("query")
        arrival_no = data.get("arrivalNo")
        document_no = data.get("documentNo")
        status = data.get("status")
        priority = data.get("priority")
        security = data.get("security")
        current_dept = data.get("currentDeptName")
        current_user = data.get("currentUserName")
        limit = data.get("limit", 10)

        results = rag_service.search_document_records(
            workspace_id=workspace_id,
            query=query,
            arrival_no=arrival_no,
            document_no=document_no,
            status=status,
            priority=priority,
            security=security,
            current_dept=current_dept,
            current_user=current_user,
            limit=limit
        )

        return jsonify({
            "statusCode": 200,
            "message": "Tìm kiếm văn bản đến thành công",
            "data": {
                "total": len(results),
                "items": results
            }
        }), 200
    except Exception as e:
        Log.error(f"[RAG-API] search_document_records error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@rag_bp.route('/api/rag/convert-excel-to-markdown', methods=['POST'])
@require_auth
def convert_excel_to_markdown_endpoint():
    """
    API tiếp nhận file Excel sổ văn bản đến và tự động chuyển đổi thành
    tài liệu Markdown có cấu trúc chuẩn (Báo cáo thống kê + Bảng tra cứu + Chi tiết từng văn bản).
    """
    try:
        from src.modules.rag.excel_converter import convert_excel_to_markdown_string

        # 1. Lấy file từ multipart/form-data hoặc từ đường dẫn file_path trong JSON
        if 'file' in request.files:
            uploaded_file = request.files['file']
            file_bytes = uploaded_file.read()
            filename = uploaded_file.filename
            markdown_content = convert_excel_to_markdown_string(file_bytes)
        else:
            data = request.json or {}
            file_path = data.get('file_path')
            if not file_path or not os.path.exists(file_path):
                return jsonify({"statusCode": 400, "message": "Vui lòng upload 'file' hoặc cung cấp 'file_path' hợp lệ"}), 400
            filename = os.path.basename(file_path)
            markdown_content = convert_excel_to_markdown_string(file_path)

        # 2. Tùy chọn: Tự động nạp luôn vào RAG nếu có workspace_id và auto_index=True
        workspace_id = request.form.get('workspace_id') or (request.json or {}).get('workspace_id')
        auto_index = (request.form.get('auto_index') or str((request.json or {}).get('auto_index', '')).lower()) in ('true', '1')

        indexed_chunks = None
        if auto_index and workspace_id:
            doc_name = filename.rsplit('.', 1)[0] + ".md"
            indexed_chunks = rag_service.index_text(
                data=markdown_content,
                workspace_id=workspace_id,
                document_name=doc_name,
                category="Văn bản đến"
            )

        return jsonify({
            "statusCode": 200,
            "message": "Chuyển đổi Excel sang Markdown thành công",
            "data": {
                "filename": filename,
                "markdown_length": len(markdown_content),
                "markdown_content": markdown_content,
                "auto_indexed": auto_index,
                "indexed_chunks": indexed_chunks
            }
        }), 200

    except Exception as e:
        Log.error(f"[RAG-API] convert_excel_to_markdown error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500





