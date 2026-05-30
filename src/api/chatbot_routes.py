from flask import Blueprint, request, jsonify, g
import os
from src.repositories.chatbot_repository import chatbot_repo
from src.repositories.workspaces_repository import workspaces_repo
from src.repositories.documents_repository import documents_repo
from src.utils.auth_middleware import require_auth
from src.utils.logger import Log
from src.config import MAX_RAG_FILE_SIZE, MAX_FILE_COUNT, MAX_DOCUMENTS_PER_WORKSPACE, DocStatus, BASE_URL, CHATBOT_EMBED_CDN_URL
from src.services.subscription_service import subscription_service
from datetime import datetime
from bson import ObjectId
from src.utils.redis_client import rag_queue
from src.tasks.document_tasks import process_document_task

chatbot_bp = Blueprint('chatbot_bp', __name__)

def format_chatbot(bot):
    if not bot:
        return None
    bot["_id"] = str(bot["_id"])
    bot["account_id"] = str(bot["account_id"])
    if bot.get("workspace_id"):
        bot["workspace_id"] = str(bot["workspace_id"])
    if isinstance(bot.get("created_at"), datetime):
        bot["created_at"] = bot["created_at"].isoformat()
    if isinstance(bot.get("updated_at"), datetime):
        bot["updated_at"] = bot["updated_at"].isoformat()
    # Make sure color and greeting are included
    bot["color"] = bot.get("color", 0)
    bot["greeting"] = bot.get("greeting", None)
    return bot

@chatbot_bp.route('/api/chatbot', methods=['POST'])
@require_auth
def create_chatbot():
    """
    Tạo chatbot mới + tạo workspace riêng + upload tài liệu cùng lúc
    Yêu cầu: multipart/form-data
    Form fields:
    - name (bắt buộc): Tên chatbot
    - description (tùy chọn): Mô tả chatbot
    - avatar_url (tùy chọn): URL avatar
    - color (tùy chọn, mặc định: 0): Màu chatbot (enum int: 0=Default, 1=Blue, 2=Green, 3=Purple, 4=Pink)
    - greeting (tùy chọn): Lời chào của chatbot
    - workspace_name (tùy chọn, mặc định: Workspace for {name}): Tên workspace mới
    - files (tùy chọn): Danh sách file upload
    """
    try:
        # Get form data (multipart/form-data)
        name = request.form.get("name")
        description = request.form.get("description")
        avatar_url = request.form.get("avatar_url")
        color = int(request.form.get("color", 0))
        greeting = request.form.get("greeting")
        workspace_name = request.form.get("workspace_name", f"Workspace for {name}")
        
        if not name:
            return jsonify({"statusCode": 400, "message": "Chatbot name is required"}), 400
        
        account_id = g.user.get("account_id")
        if not account_id:
            return jsonify({"statusCode": 400, "message": "User has no account"}), 400
        
        enqueued_docs = []
        
        # Create new workspace (1-1 with chatbot)
        workspace_id_obj = workspaces_repo.create_workspace(workspace_name, g.user_id)
        workspace_id_str = str(workspace_id_obj)
        
        # Check and save uploaded files
        files = request.files.getlist('files')
        
        if files and len(files) > 0 and files[0].filename != '':
            # Check quota
            is_allowed, msg = subscription_service.check_quota(g.user)
            if not is_allowed:
                return jsonify({"statusCode": 403, "message": f"Quota exceeded: {msg}"}), 403
            
            if len(files) > MAX_FILE_COUNT:
                return jsonify({"statusCode": 400, "message": f"Tối đa {MAX_FILE_COUNT} file mỗi lần upload"}), 400
            
            # Check file sizes
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
            current_docs = documents_repo.find_by_workspace(workspace_id_str)
            if len(list(current_docs)) + len(files) > MAX_DOCUMENTS_PER_WORKSPACE:
                 return jsonify({"statusCode": 400, "message": f"Workspace đã đạt giới hạn {MAX_DOCUMENTS_PER_WORKSPACE} tài liệu"}), 400
            
            # Save files
            from src.utils.file_utils import save_uploaded_file_list
            saved_paths = save_uploaded_file_list(files)
            
            if not saved_paths:
                 return jsonify({"statusCode": 400, "message": "No valid files saved"}), 400
            
            # Save to DB and Enqueue Task
            for idx, file_path in enumerate(saved_paths):
                original_filename = files[idx].filename
                
                # Save Initial Doc record
                doc_id = documents_repo.save_document(
                    user_id=g.user_id,
                    workspace_id=workspace_id_str,
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
                from src.utils.redis_client import publish_event
                publish_event(g.user_id, "document_status", {
                    "document_id": doc_id,
                    "status": DocStatus.UPLOADED,
                    "filename": original_filename,
                    "workspace_id": workspace_id_str,
                    "message": "Document uploaded and enqueued"
                })
                
                rag_queue.enqueue(
                    process_document_task,
                    args=(doc_id, workspace_id_str, file_path, original_filename, g.user_id),
                    kwargs={"vision_extract": True},
                    job_timeout='10m'
                )
                
                enqueued_docs.append({
                    "document_id": doc_id,
                    "filename": original_filename,
                    "status": DocStatus.UPLOADED
                })
                
                Log.info(f"[Chatbot] Enqueued document {original_filename} (ID: {doc_id})")
        
        # 3. Create chatbot linked to this workspace
        chatbot_id = chatbot_repo.create_chatbot(
            name=name,
            account_id=account_id,
            workspace_id=workspace_id_str,
            description=description,
            avatar_url=avatar_url,
            color=color,
            greeting=greeting
        )
        
        # Generate embed code
        chatbot_data = chatbot_repo.find_by_id(chatbot_id)
        public_token = chatbot_data["public_token"]
        embed_base_url = CHATBOT_EMBED_CDN_URL or BASE_URL
        embed_code = f'<script src="{embed_base_url}/chatbot-embed.js" data-chatbot-id="{chatbot_id}" data-public-token="{public_token}"></script>'
        
        return jsonify({
            "statusCode": 201,
            "message": "Chatbot created successfully" + (f" with {len(enqueued_docs)} documents enqueued" if enqueued_docs else ""),
            "data": {
                "chatbot": format_chatbot(chatbot_data),
                "embed_code": embed_code,
                "documents": enqueued_docs
            }
        }), 201
        
    except Exception as e:
        Log.error(f"[Chatbot] Create error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@chatbot_bp.route('/api/chatbot', methods=['GET'])
@require_auth
def list_chatbots():
    try:
        account_id = g.user.get("account_id")
        chatbots = chatbot_repo.find_by_account_id(account_id)
        
        formatted_bots = [format_chatbot(bot) for bot in chatbots]
        
        return jsonify({"statusCode": 200, "data": formatted_bots})
    except Exception as e:
        Log.error(f"[Chatbot] List error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@chatbot_bp.route('/api/chatbot/<chatbot_id>', methods=['GET'])
@require_auth
def get_chatbot(chatbot_id):
    try:
        # Verify ownership
        chatbot = chatbot_repo.find_by_id(chatbot_id)
        if not chatbot:
            return jsonify({"statusCode": 404, "message": "Chatbot not found"}), 404
        
        if str(chatbot["account_id"]) != str(g.user.get("account_id")):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403
        
        public_token = chatbot["public_token"]
        embed_base_url = CHATBOT_EMBED_CDN_URL or BASE_URL
        embed_code = f'<script src="{embed_base_url}/chatbot-embed.js" data-chatbot-id="{chatbot_id}" data-public-token="{public_token}"></script>'
        
        formatted_bot = format_chatbot(chatbot)
        formatted_bot["embed_code"] = embed_code
        
        return jsonify({"statusCode": 200, "data": formatted_bot})
    except Exception as e:
        Log.error(f"[Chatbot] Get error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@chatbot_bp.route('/api/chatbot/<chatbot_id>', methods=['PUT'])
@require_auth
def update_chatbot(chatbot_id):
    try:
        # Verify ownership
        chatbot = chatbot_repo.find_by_id(chatbot_id)
        if not chatbot:
            return jsonify({"statusCode": 404, "message": "Chatbot not found"}), 404
        
        if str(chatbot["account_id"]) != str(g.user.get("account_id")):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403
        
        # Get update data
        data = request.json or {}
        update_data = {"updated_at": datetime.utcnow()}
        
        if "name" in data:
            update_data["name"] = data["name"]
        if "description" in data:
            update_data["description"] = data["description"]
        if "avatar_url" in data:
            update_data["avatar_url"] = data["avatar_url"]
        if "color" in data:
            update_data["color"] = data["color"]
        if "greeting" in data:
            update_data["greeting"] = data["greeting"]
        
        # Update workspace_id with 1-1 check
        if "workspace_id" in data:
            new_workspace_id = data["workspace_id"]
            if new_workspace_id:
                # Check if this workspace is already used by another chatbot
                existing_chatbot = chatbot_repo.find_one({
                    "workspace_id": ObjectId(new_workspace_id),
                    "_id": {"$ne": ObjectId(chatbot_id)}
                })
                if existing_chatbot:
                    return jsonify({"statusCode": 400, "message": "Workspace này đã được dùng bởi một chatbot khác"}), 400
                update_data["workspace_id"] = ObjectId(new_workspace_id)
            else:
                update_data["workspace_id"] = None
        
        # Update chatbot
        chatbot_repo.update(chatbot_id, update_data)
        
        # Return updated chatbot
        updated_bot = chatbot_repo.find_by_id(chatbot_id)
        
        return jsonify({
            "statusCode": 200, 
            "message": "Chatbot updated successfully",
            "data": format_chatbot(updated_bot)
        })
    except ValueError as e:
        return jsonify({"statusCode": 400, "message": str(e)}), 400
    except Exception as e:
        Log.error(f"[Chatbot] Update error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@chatbot_bp.route('/api/chatbot/<chatbot_id>', methods=['DELETE'])
@require_auth
def delete_chatbot(chatbot_id):
    try:
        # Verify ownership
        chatbot = chatbot_repo.find_by_id(chatbot_id)
        if not chatbot:
            return jsonify({"statusCode": 404, "message": "Chatbot not found"}), 404
        
        if str(chatbot["account_id"]) != str(g.user.get("account_id")):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403
        
        # Soft delete
        chatbot_repo.update(chatbot_id, {"is_active": False})
        
        return jsonify({"statusCode": 200, "message": "Chatbot deleted successfully"})
    except Exception as e:
        Log.error(f"[Chatbot] Delete error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500
