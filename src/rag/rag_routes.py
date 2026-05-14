from flask import Blueprint, request, jsonify, g
import os
from src.utils.auth_middleware import require_auth
from src.repositories.workspaces_repository import workspaces_repo
from src.repositories.chat_history_repository import chat_history_repo
from src.repositories.documents_repository import documents_repo
from src.repositories.extraction_logs_repository import extraction_logs_repo
from src.rag.rag_service import rag_service
from src.rag.qdrant_service import qdrant_service
from src.utils.redis_client import rag_queue
from src.tasks.document_tasks import process_document_task
from src.utils.logger import Log
from src.config import MAX_RAG_FILE_SIZE, MAX_FILE_COUNT, MAX_DOCUMENTS_PER_WORKSPACE, DocStatus
from src.services.subscription_service import subscription_service
from src.repositories.accounts_repository import accounts_repo

rag_bp = Blueprint('rag_bp', __name__)

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
        # Verify workspace belongs to user
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not workspace or workspace['user_id'] != g.user_id:
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
        # Verify workspace belongs to user
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not workspace or workspace['user_id'] != g.user_id:
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
        # 1. Verify workspace exists and belongs to user
        workspace = workspaces_repo.find_workspace_by_id(workspace_id)
        if not workspace:
            return jsonify({"statusCode": 404, "message": "Workspace not found"}), 404
            
        if workspace['user_id'] != g.user_id:
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
        if not workspace or workspace['user_id'] != g.user_id:
            return jsonify({"statusCode": 403, "message": "Access denied to workspace"}), 403

        is_allowed, msg = subscription_service.check_quota(g.user)
        if not is_allowed:
            return jsonify({"statusCode": 403, "message": f"Quota exceeded: {msg}"}), 403
            
        # 2. Get files
        files = request.files.getlist('files')
        if not files:
            return jsonify({"statusCode": 400, "message": "No files uploaded"}), 400
            
        if len(files) > MAX_FILE_COUNT:
            return jsonify({"statusCode": 400, "message": f"Tối đa {MAX_FILE_COUNT} file mỗi lần upload"}), 400

        # 3. Check individual file size
        for file in files:
            # Di chuyển con trỏ đến cuối file để lấy kích thước
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0) # Đưa con trỏ về đầu file để có thể đọc sau này
            
            if file_size > MAX_RAG_FILE_SIZE:
                 return jsonify({
                     "statusCode": 413, 
                     "message": f"File '{file.filename}' quá lớn. Giới hạn {MAX_RAG_FILE_SIZE/1024/1024}MB"
                 }), 413

        # Check document limit
        current_docs = documents_repo.find_by_workspace(workspace_id)
        if len(list(current_docs)) >= MAX_DOCUMENTS_PER_WORKSPACE:
             return jsonify({"statusCode": 400, "message": f"Workspace đã đạt giới hạn {MAX_DOCUMENTS_PER_WORKSPACE} tài liệu"}), 400

        from src.utils.file_utils import save_uploaded_file_list
        saved_paths = save_uploaded_file_list(files)
        
        if not saved_paths:
             return jsonify({"statusCode": 400, "message": "No valid files saved"}), 400

        enqueued_docs = []

        # 3. Save to DB and Enqueue Task
        for idx, file_path in enumerate(saved_paths):
            original_filename = files[idx].filename
            
            # Save Initial Doc record (kèm source_files để ownership check)
            doc_id = documents_repo.save_document(
                user_id=g.user_id,
                workspace_id=workspace_id,
                filename=original_filename,
                status=DocStatus.UPLOADED,
                source_files=[
                    {
                        "file_name": os.path.basename(file_path),
                        "storage_path": file_path.replace("\\", "/")
                    }
                ]
            )
            
            # Enqueue Background Task
            # retry=Retry(max=3) # Optional: RQ retry logic
            from src.utils.redis_client import publish_event
            publish_event(g.user_id, "document_status", {
                "document_id": doc_id,
                "status": DocStatus.UPLOADED,
                "filename": original_filename,
                "workspace_id": workspace_id,
                "message": "Document uploaded and enqueued"
            })

            rag_queue.enqueue(
                process_document_task,
                args=(doc_id, workspace_id, file_path, original_filename, g.user_id),
                job_timeout='10m' # Allow up to 10 mins for heavy OCR
            )
            
            enqueued_docs.append({
                "document_id": doc_id,
                "filename": original_filename,
                "status": DocStatus.UPLOADED
            })
            
            Log.info(f"[RAG-API] Enqueued document {original_filename} (ID: {doc_id})")

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
        if not workspace or workspace['user_id'] != g.user_id:
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403
            
        documents = documents_repo.find_by_workspace(workspace_id)
        # Convert ObjectId to string
        for doc in documents:
            doc["_id"] = str(doc["_id"])
            if "user_id" in doc: doc["user_id"] = str(doc["user_id"])
            
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
            
        if str(doc['user_id']) != g.user_id:
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
        if not workspace or workspace['user_id'] != g.user_id:
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        data = request.json
        question = data.get('question')
        provider = data.get('provider', 'auto')
        
        if not question:
            return jsonify({"statusCode": 400, "message": "Question is required"}), 400
            
        # Check quota
        is_allowed, msg = subscription_service.check_quota(g.user)
        if not is_allowed:
            return jsonify({"statusCode": 403, "message": msg}), 403

        # Increment usage
        if g.user.get('account_id'):
            accounts_repo.increment_usage(g.user.get('account_id'))

        result = rag_service.query(question, workspace_id, provider=provider)
        
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
        if not workspace or workspace['user_id'] != g.user_id:
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403

        suggestions = rag_service.suggest_questions(workspace_id)
        
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
        if not workspace or workspace['user_id'] != g.user_id:
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
        if not workspace or workspace['user_id'] != g.user_id:
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
