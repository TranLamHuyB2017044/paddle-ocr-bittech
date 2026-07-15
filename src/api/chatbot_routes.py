from flask import Blueprint, request, jsonify, g
import os
from src.repositories.chatbot_repository import chatbot_repo
from src.repositories.workspaces_repository import workspaces_repo
from src.repositories.documents_repository import documents_repo
from src.repositories.chat_history_repository import chat_history_repo
from src.utils.auth_middleware import require_auth
from src.utils.logger import Log
from src.config import MAX_RAG_FILE_SIZE, MAX_FILE_COUNT, MAX_DOCUMENTS_PER_WORKSPACE, DocStatus, BASE_URL, CHATBOT_EMBED_CDN_URL, PLANS_CONFIG, N8N_WEBHOOK_URL
from src.services.subscription_service import subscription_service
from datetime import datetime
from bson import ObjectId
from src.utils.redis_client import rag_queue
from src.tasks.document_tasks import process_document_task
from src.utils.rate_limit import limiter
from src.models.schemas import ChatbotUpdateRequest
from pydantic import ValidationError

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
    # Make sure color, greeting and Telegram fields are included
    bot["color"] = bot.get("color", 0)
    bot["greeting"] = bot.get("greeting", None)
    bot["telegram_bot_token"] = bot.get("telegram_bot_token", None)
    bot["telegram_chat_id"] = bot.get("telegram_chat_id", None)
    bot["workflow_webhook_url"] = bot.get("workflow_webhook_url", None)
    bot["collect_contact_info"] = bot.get("collect_contact_info", True)
    return bot

@chatbot_bp.route('/api/chatbot', methods=['POST'])
@require_auth
@limiter.limit("30 per minute")
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
        color_str = request.form.get("color")
        try:
            color = int(color_str) if color_str and color_str.strip() else 0
        except (ValueError, TypeError):
            color = 0
        greeting = request.form.get("greeting")
        telegram_bot_token = request.form.get("telegram_bot_token")
        telegram_chat_id = request.form.get("telegram_chat_id")
        collect_contact_info_str = request.form.get("collect_contact_info", "true")
        collect_contact_info = collect_contact_info_str in ["1", "true", "True", "yes"]
        n8n_str = request.form.get("n8n", "0")
        n8n = n8n_str in ["1", "true", "True", "yes"]
        if n8n:
            workflow_webhook_url = N8N_WEBHOOK_URL
        else:
            workflow_webhook_url = None
        workspace_name = request.form.get("workspace_name", f"Workspace for {name}" if name else None)
        
        # Validate required fields and color
        if not name:
            return jsonify({"statusCode": 400, "message": "Chatbot name is required"}), 400
        if not (0 <= color <= 4):
            return jsonify({"statusCode": 400, "message": "Color must be between 0 and 4"}), 400
        
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
                
                # Chỉ sử dụng vision_extract khi truyền cờ 'vision' bằng True (mặc định ưu tiên deepdoc và viet ocr)
                vision_extract = request.args.get('vision', 'false').lower() == 'true' or request.form.get('vision', 'false').lower() == 'true'
                
                rag_queue.enqueue(
                    process_document_task,
                    args=(doc_id, workspace_id_str, file_path, original_filename, g.user_id),
                    kwargs={"vision_extract": vision_extract},
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
            greeting=greeting,
            telegram_bot_token=telegram_bot_token,
            telegram_chat_id=telegram_chat_id,
            workflow_webhook_url=workflow_webhook_url,
            collect_contact_info=collect_contact_info
        )
        
        # Generate embed code
        chatbot_data = chatbot_repo.find_by_id(chatbot_id)
        if not chatbot_data:
            return jsonify({"statusCode": 500, "message": "Failed to retrieve created chatbot"}), 500
            
        public_token = chatbot_data["public_token"]
        embed_base_url = (CHATBOT_EMBED_CDN_URL or BASE_URL).rstrip('/')
        
        # Choose the right embed script based on whether n8n is enabled
        if chatbot_data.get("workflow_webhook_url"):
            embed_code = f'<script src="{embed_base_url}/chatbot-embed-n8n.js" data-chatbot-id="{chatbot_id}" data-public-token="{public_token}" data-webhook-url="{chatbot_data["workflow_webhook_url"]}"></script>'
        else:
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
@limiter.limit("100 per minute")
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
        embed_base_url = (CHATBOT_EMBED_CDN_URL or BASE_URL).rstrip('/')
        
        # Choose the right embed script based on whether n8n is enabled
        if chatbot.get("workflow_webhook_url"):
            embed_code = f'<script src="{embed_base_url}/chatbot-embed-n8n.js" data-chatbot-id="{chatbot_id}" data-public-token="{public_token}" data-webhook-url="{chatbot["workflow_webhook_url"]}"></script>'
        else:
            embed_code = f'<script src="{embed_base_url}/chatbot-embed.js" data-chatbot-id="{chatbot_id}" data-public-token="{public_token}"></script>'
        
        formatted_bot = format_chatbot(chatbot)
        formatted_bot["embed_code"] = embed_code
        
        return jsonify({"statusCode": 200, "data": formatted_bot})
    except Exception as e:
        Log.error(f"[Chatbot] Get error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@chatbot_bp.route('/api/chatbot/<chatbot_id>', methods=['PUT'])
@require_auth
@limiter.limit("30 per minute")
def update_chatbot(chatbot_id):
    try:
        # Verify ownership
        chatbot = chatbot_repo.find_by_id(chatbot_id)
        if not chatbot:
            return jsonify({"statusCode": 404, "message": "Chatbot not found"}), 404
        
        if str(chatbot["account_id"]) != str(g.user.get("account_id")):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403
        
        # Validate update data with Pydantic
        data = request.json or {}
        try:
            validated_data = ChatbotUpdateRequest(**data)
        except ValidationError as e:
            return jsonify({"statusCode": 400, "message": "Invalid input", "errors": e.errors()}), 400
        
        # Build update data
        update_data = {"updated_at": datetime.utcnow()}
        if validated_data.name is not None:
            update_data["name"] = validated_data.name
        if validated_data.description is not None:
            update_data["description"] = validated_data.description
        if validated_data.avatar_url is not None:
            update_data["avatar_url"] = validated_data.avatar_url
        if validated_data.color is not None:
            update_data["color"] = validated_data.color
        if validated_data.greeting is not None:
            update_data["greeting"] = validated_data.greeting
        if validated_data.telegram_bot_token is not None:
            update_data["telegram_bot_token"] = validated_data.telegram_bot_token
        if validated_data.telegram_chat_id is not None:
            update_data["telegram_chat_id"] = validated_data.telegram_chat_id
        if validated_data.workflow_webhook_url is not None:
            update_data["workflow_webhook_url"] = validated_data.workflow_webhook_url
        if validated_data.collect_contact_info is not None:
            update_data["collect_contact_info"] = validated_data.collect_contact_info
        
        # Update workspace_id with 1-1 check
        if validated_data.workspace_id is not None:
            new_workspace_id = validated_data.workspace_id
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
@limiter.limit("30 per minute")
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

@chatbot_bp.route('/api/chatbot/<chatbot_id>/analytics', methods=['GET'])
@require_auth
@limiter.limit("100 per minute")
def get_chatbot_analytics(chatbot_id):
    try:
        # Verify ownership
        chatbot = chatbot_repo.find_by_id(chatbot_id)
        if not chatbot:
            return jsonify({"statusCode": 404, "message": "Chatbot not found"}), 404
        
        if str(chatbot["account_id"]) != str(g.user.get("account_id")):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403
        
        workspace_id = str(chatbot["workspace_id"]) if chatbot.get("workspace_id") else None
        
        # Get quota info - from account, not from user!
        from src.repositories.accounts_repository import accounts_repo
        account_id = g.user.get("account_id")
        account = accounts_repo.find_by_id(account_id) if account_id else None
        if not account:
            return jsonify({"statusCode": 404, "message": "Account not found"}), 404
        
        plan_key = account.get("plan", 0)
        plan_config = PLANS_CONFIG.get(plan_key, {})
        max_requests = plan_config.get("max_requests_per_month", 0)
        used_requests = account.get("used_requests", 0)
        
        # Get analytics
        analytics = {
            "quota": {
                "used": used_requests,
                "max": max_requests,
                "is_unlimited": plan_config.get("is_unlimited", False),
                "remaining": max_requests - used_requests if not plan_config.get("is_unlimited", False) else "Unlimited"
            },
            "message_counts": {
                "today": chat_history_repo.get_message_count_by_period(workspace_id, "day") if workspace_id else 0,
                "week": chat_history_repo.get_message_count_by_period(workspace_id, "week") if workspace_id else 0,
                "month": chat_history_repo.get_message_count_by_period(workspace_id, "month") if workspace_id else 0
            },
            "latest_message": chat_history_repo.get_latest_message(workspace_id) if workspace_id else None,
            "top_keywords": {
                "today": chat_history_repo.get_top_keywords(workspace_id, "day") if workspace_id else [],
                "week": chat_history_repo.get_top_keywords(workspace_id, "week") if workspace_id else [],
                "month": chat_history_repo.get_top_keywords(workspace_id, "month") if workspace_id else []
            }
        }
        
        return jsonify({"statusCode": 200, "data": analytics})
    except Exception as e:
        Log.error(f"[Chatbot Analytics] Error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@chatbot_bp.route('/api/chatbot/<chatbot_id>/sessions', methods=['GET'])
@require_auth
@limiter.limit("100 per minute")
def get_chatbot_sessions(chatbot_id):
    try:
        # Verify ownership
        chatbot = chatbot_repo.find_by_id(chatbot_id)
        if not chatbot:
            return jsonify({"statusCode": 404, "message": "Chatbot not found"}), 404
        
        if str(chatbot["account_id"]) != str(g.user.get("account_id")):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403
        
        workspace_id = str(chatbot["workspace_id"]) if chatbot.get("workspace_id") else None
        
        if not workspace_id:
            return jsonify({"statusCode": 200, "data": []})
        
        sessions = chat_history_repo.get_all_sessions(workspace_id, limit=50)
        return jsonify({"statusCode": 200, "data": sessions})
    except Exception as e:
        Log.error(f"[Chatbot Sessions] Error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@chatbot_bp.route('/api/chatbot/<chatbot_id>/sessions/<session_id>', methods=['GET'])
@require_auth
@limiter.limit("100 per minute")
def get_chatbot_session_history(chatbot_id, session_id):
    try:
        # Verify ownership
        chatbot = chatbot_repo.find_by_id(chatbot_id)
        if not chatbot:
            return jsonify({"statusCode": 404, "message": "Chatbot not found"}), 404
        
        if str(chatbot["account_id"]) != str(g.user.get("account_id")):
            return jsonify({"statusCode": 403, "message": "Access denied"}), 403
        
        history = chat_history_repo.get_session_history(session_id, limit=100)
        return jsonify({"statusCode": 200, "data": history})
    except Exception as e:
        Log.error(f"[Chatbot Session History] Error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500
