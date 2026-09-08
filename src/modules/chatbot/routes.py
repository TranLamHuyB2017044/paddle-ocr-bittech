"""
Chatbot Module Routes
Consolidated route handlers for Chatbot Management, Public Chat Widget, Embedded JS Scripts, and Admin Chatbot Analytics.
"""
import os
import re
import secrets
import traceback
from math import ceil
from datetime import datetime

from flask import Blueprint, request, jsonify, g, send_from_directory, current_app
from pydantic import ValidationError

from src.modules.chatbot.repositories import chatbot_repo, chat_history_repo
from src.modules.auth.repositories.workspaces_repository import workspaces_repo
from src.modules.ocr.repositories.documents_repository import documents_repo
from src.modules.auth.repositories.users_repository import users_repo
from src.modules.auth.repositories.accounts_repository import accounts_repo
from src.shared.services.subscription_service import subscription_service
from src.shared.utils.auth_middleware import require_auth
from src.shared.utils.logger import Log
from src.shared.utils.rate_limit import limiter
from src.shared.utils.redis_client import rag_queue
from src.modules.ocr.models.schemas import ChatbotUpdateRequest
import src.core.config as config
from src.core.config import (
    MAX_RAG_FILE_SIZE, MAX_FILE_COUNT, MAX_DOCUMENTS_PER_WORKSPACE,
    DocStatus, BASE_URL, CHATBOT_EMBED_CDN_URL, PLANS_CONFIG, N8N_WEBHOOK_URL
)

chatbot_bp = Blueprint('chatbot_bp', __name__)

# State management for public contact info collection
waiting_for_contact = {}
customer_contact_info = {}
last_question_before_contact = {}


def parse_bool(value, default=True):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in ("true", "1", "yes")


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
    bot["color"] = bot.get("color", 0)
    bot["domain"] = bot.get("domain", "ecommerce")
    bot["greeting"] = bot.get("greeting", None)
    bot["telegram_bot_token"] = bot.get("telegram_bot_token", None)
    bot["telegram_chat_id"] = bot.get("telegram_chat_id", None)
    bot["workflow_webhook_url"] = bot.get("workflow_webhook_url", None)
    default_collect = False if bot.get("domain") == "ocop" else True
    bot["collect_contact_info"] = bot.get("collect_contact_info", default_collect)
    return bot


def extract_contact_info(text):
    info = {}
    pattern = r'tôi tên là\s+(.+?)\s*(?:-|,|;)?\s*(?:sđt|sdt|số điện thoại|so dien thoai)\s*[:\-]?\s*((?:\+?84|0)(?:3[2-9]|5[2689]|7[06-9]|8[1-9]|9[0-46-9])[-.\s]?[0-9]{3}[-.\s]?[0-9]{4})'
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if match:
        name = match.group(1).strip()
        phone = match.group(2).strip()
        normalized_phone = re.sub(r'[-.\s]', '', phone)
        if len(name) >= 2:
            info["name"] = name
        info["phone"] = normalized_phone
    return info


def analyze_contact_info_error(text):
    text_lower = text.lower()
    has_name_prefix = "tôi tên là" in text_lower
    has_phone_keyword = any(keyword in text_lower for keyword in ["sđt", "sdt", "số điện thoại", "so dien thoai"])
    
    potential_name = None
    if has_name_prefix:
        name_match = re.search(r'tôi tên là\s+(.+?)(?:\s*(?:-|,|;|:|$))', text, flags=re.IGNORECASE)
        if name_match:
            potential_name = name_match.group(1).strip()
    
    potential_phone = None
    phone_matches = re.findall(r'(?:\+?84|0)[0-9\-.\s]{8,12}', text)
    if phone_matches:
        potential_phone = phone_matches[0]
    
    errors = []
    if not has_name_prefix:
        errors.append("Thiếu từ khóa \"Tôi tên là\"")
    elif potential_name and len(potential_name) < 2:
        errors.append("Tên quá ngắn (cần ít nhất 2 ký tự)")
    
    if not has_phone_keyword:
        errors.append("Thiếu từ khóa \"sđt\" hoặc \"số điện thoại\"")
    elif not potential_phone:
        errors.append("Không tìm thấy số điện thoại hợp lệ")
    else:
        normalized_phone = re.sub(r'[-.\s]', '', potential_phone)
        if len(normalized_phone) not in [9, 10] and not normalized_phone.startswith('+84') and len(normalized_phone) not in [11, 12]:
            errors.append("Số điện thoại phải có 9-10 số (hoặc 11-12 số nếu có +84)")
        elif not re.match(r'(?:\+?84|0)(?:3[2-9]|5[2689]|7[06-9]|8[1-9]|9[0-46-9])', normalized_phone):
            errors.append("Số điện thoại không đúng định dạng đầu số Việt Nam")
    
    return errors


# ── 1. PUBLIC CHAT & EMBED ENDPOINTS ─────────────────────────────────────────

@chatbot_bp.route('/api/public/chatbot/<chatbot_id>', methods=['GET'])
@limiter.limit("100 per minute")
def get_public_chatbot_details(chatbot_id):
    try:
        public_token = request.headers.get('x-public-token')
        if not public_token:
            return jsonify({"statusCode": 401, "message": "Missing x-public-token header"}), 401
        
        chatbot = chatbot_repo.find_by_public_token(public_token)
        if not chatbot or str(chatbot["_id"]) != chatbot_id:
            return jsonify({"statusCode": 403, "message": "Invalid chatbot or token"}), 403
        
        formatted = {
            "_id": str(chatbot["_id"]),
            "name": chatbot["name"],
            "description": chatbot.get("description"),
            "avatar_url": chatbot.get("avatar_url"),
            "color": chatbot.get("color", 0),
            "domain": chatbot.get("domain", "ecommerce"),
            "greeting": chatbot.get("greeting"),
            "workspace_id": str(chatbot["workspace_id"]) if chatbot.get("workspace_id") else None,
            "workflow_webhook_url": chatbot.get("workflow_webhook_url"),
            "collect_contact_info": chatbot.get("collect_contact_info", False if chatbot.get("domain") == "ocop" else True)
        }
        return jsonify({"statusCode": 200, "data": formatted})
    except Exception as e:
        Log.error(f"[Public Chatbot Details] Error: {e}")
        return jsonify({"statusCode": 500, "message": "Internal server error"}), 500


@chatbot_bp.route('/api/public/chatbot/<chatbot_id>/chat', methods=['POST'])
@limiter.limit("50 per minute")
def public_chat_with_chatbot(chatbot_id):
    global waiting_for_contact, customer_contact_info, last_question_before_contact
    try:
        public_token = request.headers.get('x-public-token')
        if not public_token:
            return jsonify({"statusCode": 401, "message": "Missing x-public-token header"}), 401
        
        chatbot = chatbot_repo.find_by_public_token(public_token)
        if not chatbot or str(chatbot["_id"]) != chatbot_id:
            return jsonify({"statusCode": 403, "message": "Invalid chatbot or token"}), 403
        
        account = accounts_repo.find_by_id(chatbot["account_id"])
        if not account:
            return jsonify({"statusCode": 404, "message": "Account not found"}), 404
        
        # Temporarily bypass quota check for unlimited chatbot requests
        # plan_key = account.get("plan", 0)
        # plan_cfg = PLANS_CONFIG.get(plan_key, {})
        # if not plan_cfg.get("is_unlimited", False):
        #     max_requests = plan_cfg.get("max_requests_per_month", 0)
        #     used_requests = account.get("used_requests", 0)
        #     if used_requests + 1 > max_requests:
        #         return jsonify({"statusCode": 403, "message": f"Quota exceeded: {used_requests}/{max_requests}"}), 403
        
        data = request.json or {}
        message = data.get("message")
        session_id = data.get("session_id") or data.get("sessionId") or secrets.token_urlsafe(16)
        
        if not message:
            return jsonify({"statusCode": 400, "message": "Message is required"}), 400
        
        domain = chatbot.get("domain", "ecommerce")
        collect_contact = chatbot.get("collect_contact_info", False if domain == "ocop" else True)
        result = {"answer": "", "provider": "echo"}
        is_contact_info_reply = False
        
        # Check if the message contains contact info (only if collect_contact is enabled for this bot)
        info = extract_contact_info(message) if collect_contact else {}
        if info.get("name") and info.get("phone"):
            is_contact_info_reply = True
            customer_contact_info[session_id] = info
            waiting_for_contact[session_id] = False
            
            confirmation_text = f"Tôi đã tiếp nhận thông tin và chuyển đến nhân viên phụ trách, họ sẽ liên hệ lại sớm nhất!\nHọ tên: {info['name']}\nSĐT: {info['phone']}"
            result["answer"] = confirmation_text
            
            if chatbot.get("telegram_bot_token") and chatbot.get("telegram_chat_id"):
                try:
                    from src.shared.services.telegram_service import send_telegram_message, format_customer_question_notification
                    original_question = last_question_before_contact.get(session_id, "Không có câu hỏi trước đó")
                    full_message = format_customer_question_notification(original_question, chatbot.get("name", "Chatbot"))
                    full_message += f"\n\n🏷️ Lĩnh vực: {domain.upper()}\n🔑 Session ID: {session_id}\n\n📞 Thông tin liên hệ:\nHọ tên: {info['name']}\nSĐT: {info['phone']}"
                    send_telegram_message(chatbot["telegram_bot_token"], chatbot["telegram_chat_id"], full_message)
                except Exception as e:
                    Log.error(f"[Public Chat] Telegram send error: {e}")
        elif collect_contact and session_id in waiting_for_contact and waiting_for_contact[session_id]:
            # For bots collecting contact info, provide validation guidance when input was incomplete
            errors = analyze_contact_info_error(message)
            if errors:
                result["answer"] = "Thông tin chưa đúng định dạng! Lỗi:\n- " + "\n- ".join(errors)
            else:
                result["answer"] = "Vui lòng cung cấp thông tin theo định dạng để liên hệ nhân viên: Tôi tên là [tên] - sđt [số điện thoại]"
            result["answer"] += "\n\nVí dụ đúng: Tôi tên là Nguyễn Văn A - sđt 0912345678"
        else:
            if session_id in waiting_for_contact:
                waiting_for_contact[session_id] = False

            question_lower = message.lower().strip()
            if any(q in question_lower for q in ["bạn là ai", "bạn là ai?", "bạn là ai ?"]):
                if domain == "ocop":
                    result["answer"] = "Tôi là trợ lý ảo hỗ trợ quy trình chấm điểm và hướng dẫn sử dụng phần mềm OCOP!"
                elif domain == "customer_support":
                    result["answer"] = "Tôi là trợ lý hỗ trợ kỹ thuật và chăm sóc khách hàng!"
                elif domain == "ecommerce":
                    result["answer"] = "Tôi là chatbot tư vấn và chăm sóc khách hàng!"
                else:
                    result["answer"] = f"Tôi là {chatbot.get('name', 'trợ lý ảo')}!"
            else:
                contact_request_keywords = ["liên hệ nhân viên", "hãy liên hệ", "nhân viên hỗ trợ", "liên hệ với nhân viên", "gọi nhân viên", "mua sỉ", "làm đại lý"]
                is_contact_request = any(keyword.lower() in message.lower() for keyword in contact_request_keywords)
                
                if chatbot.get("workspace_id") and not (is_contact_request and collect_contact):
                    from src.modules.rag.rag_service import rag_service
                    result = rag_service.chat_store(
                        question=message,
                        workspace_id=str(chatbot["workspace_id"]),
                        telegram_bot_token=None,
                        telegram_chat_id=None,
                        chatbot_name=chatbot.get("name", "Chatbot"),
                        domain=domain
                    )
                    
                    no_info_keywords = ["không có thông tin", "không tìm thấy", "không biết"]
                    is_no_info = any(keyword.lower() in result["answer"].lower() for keyword in no_info_keywords)
                    
                    if is_no_info and collect_contact:
                        result["answer"] += "\n\nVui lòng cung cấp thông tin theo định dạng để liên hệ nhân viên: Tôi tên là [tên] - sđt [số điện thoại]"
                        waiting_for_contact[session_id] = True
                        last_question_before_contact[session_id] = message
                else:
                    if is_contact_request and collect_contact:
                        result["answer"] = "Vui lòng cung cấp thông tin theo định dạng để liên hệ hỗ trợ: Tôi tên là [tên] - sđt [số điện thoại]"
                        waiting_for_contact[session_id] = True
                        last_question_before_contact[session_id] = message
                    else:
                        result["answer"] = f"Cảm ơn bạn đã hỏi: {message}"
        
        if not is_contact_info_reply:
            accounts_repo.increment_usage(chatbot["account_id"])
        
        chat_history_repo.save_message(
            workspace_id=chatbot.get("workspace_id"),
            user_id="anonymous",
            question=message,
            answer=result["answer"],
            sources=result.get("sources"),
            provider=result.get("provider"),
            session_id=session_id,
            customer_info=customer_contact_info.get(session_id, {})
        )
        
        waiting_state = waiting_for_contact.get(session_id, False) if collect_contact else False
        return jsonify({"statusCode": 200, "data": {**result, "sessionId": session_id, "waitingForContact": waiting_state}})
    except Exception as e:
        Log.error(f"[Public Chat] Error: {e}")
        return jsonify({"statusCode": 500, "message": "Internal server error"}), 500


@chatbot_bp.route('/api/public/chatbot/<chatbot_id>/suggest', methods=['GET'])
@limiter.limit("100 per minute")
def get_public_chatbot_suggestions(chatbot_id):
    try:
        public_token = request.headers.get('x-public-token')
        if not public_token:
            return jsonify({"statusCode": 401, "message": "Missing x-public-token header"}), 401
        
        chatbot = chatbot_repo.find_by_public_token(public_token)
        if not chatbot or str(chatbot["_id"]) != chatbot_id:
            return jsonify({"statusCode": 403, "message": "Invalid chatbot or token"}), 403
        
        if not chatbot.get("workspace_id"):
            return jsonify({"statusCode": 200, "data": {"suggestions": []}})
        
        from src.modules.rag.rag_service import rag_service
        suggestions = rag_service.suggest_questions(str(chatbot["workspace_id"]))
        return jsonify({"statusCode": 200, "data": {"suggestions": suggestions}})
    except Exception as e:
        Log.error(f"[Public Suggestions] Error: {e}")
        return jsonify({"statusCode": 500, "message": "Internal server error"}), 500


@chatbot_bp.route('/chatbot-embed.js', methods=['GET'])
@limiter.limit("200 per minute")
def get_embed_script():
    try:
        public_dir = os.path.join(current_app.root_path, 'public')
        return send_from_directory(public_dir, 'chatbot-embed.js', mimetype='application/javascript')
    except Exception as e:
        Log.error(f"[Embed Script] Error serving script: {e}")
        return "Script not found", 404


@chatbot_bp.route('/chatbot-embed-n8n.js', methods=['GET'])
@limiter.limit("200 per minute")
def get_embed_script_n8n():
    try:
        public_dir = os.path.join(current_app.root_path, 'public')
        return send_from_directory(public_dir, 'chatbot-embed-n8n.js', mimetype='application/javascript')
    except Exception as e:
        Log.error(f"[Embed Script n8n] Error serving script: {e}")
        return "Script not found", 404


# ── 2. CHATBOT CRUD ENDPOINTS ────────────────────────────────────────────────

@chatbot_bp.route('/api/chatbot', methods=['POST'])
@require_auth
@limiter.limit("30 per minute")
def create_chatbot():
    try:
        payload = request.get_json(silent=True) or request.form.to_dict() or {}
        name = payload.get("name")
        if not name or not str(name).strip():
            return jsonify({"statusCode": 400, "message": "Field 'name' is required"}), 400

        user = g.user
        account_id = user.get("account_id")
        domain = str(payload.get("domain", "ecommerce")).strip().lower()

        # Check if collect_contact_info is explicitly specified for this chatbot (supports any domain/type)
        raw_collect = payload.get("collect_contact_info")
        if raw_collect is None:
            raw_collect = payload.get("collect_contact")
        
        default_collect = False if domain == "ocop" else True
        collect_contact_info = parse_bool(raw_collect, default=default_collect)

        ws_name = f"Workspace-{str(name).strip()}"
        ws_id = workspaces_repo.create_workspace(ws_name, user_id=g.user_id, account_id=account_id)

        bot_id = chatbot_repo.create_chatbot(
            account_id=account_id,
            workspace_id=ws_id,
            name=str(name).strip(),
            domain=domain,
            description=str(payload.get("description", "")).strip() or None,
            avatar_url=str(payload.get("avatar_url", "")).strip() or None,
            greeting=str(payload.get("greeting", "")).strip() or None,
            color=int(payload.get("color", 0)),
            telegram_bot_token=str(payload.get("telegram_bot_token", "")).strip() or None,
            telegram_chat_id=str(payload.get("telegram_chat_id", "")).strip() or None,
            workflow_webhook_url=str(payload.get("workflow_webhook_url", "")).strip() or None,
            collect_contact_info=collect_contact_info
        )

        bot = chatbot_repo.find_by_id(bot_id)
        return jsonify({"statusCode": 201, "message": "Chatbot created successfully", "data": format_chatbot(bot)}), 201
    except Exception as e:
        Log.error(f"[ChatbotAPI] Create chatbot error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@chatbot_bp.route('/api/chatbot/my-chatbots', methods=['GET'])
@require_auth
def get_my_chatbots():
    try:
        user = g.user
        account_id = user.get("account_id")
        bots = chatbot_repo.find_by_account_id(account_id)
        formatted = [format_chatbot(b) for b in bots]
        return jsonify({"statusCode": 200, "data": formatted})
    except Exception as e:
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@chatbot_bp.route('/api/chatbot/<chatbot_id>', methods=['GET'])
@require_auth
def get_chatbot_detail_user(chatbot_id):
    try:
        bot = chatbot_repo.find_by_id(chatbot_id)
        if not bot:
            return jsonify({"statusCode": 404, "message": "Chatbot not found"}), 404
        return jsonify({"statusCode": 200, "data": format_chatbot(bot)})
    except Exception as e:
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@chatbot_bp.route('/api/chatbot/<chatbot_id>', methods=['PUT'])
@require_auth
def update_chatbot_user(chatbot_id):
    try:
        bot = chatbot_repo.find_by_id(chatbot_id)
        if not bot:
            return jsonify({"statusCode": 404, "message": "Chatbot not found"}), 404

        data = request.json or {}
        update_data = {}
        for k in ["name", "description", "avatar_url", "greeting", "color", "telegram_bot_token", "telegram_chat_id", "workflow_webhook_url", "domain"]:
            if k in data:
                update_data[k] = data[k]

        if "collect_contact_info" in data:
            update_data["collect_contact_info"] = parse_bool(data["collect_contact_info"])
        elif "collect_contact" in data:
            update_data["collect_contact_info"] = parse_bool(data["collect_contact"])

        success = chatbot_repo.update_chatbot(chatbot_id, update_data)
        if success:
            updated = chatbot_repo.find_by_id(chatbot_id)
            return jsonify({"statusCode": 200, "message": "Updated successfully", "data": format_chatbot(updated)})
        return jsonify({"statusCode": 400, "message": "Update failed"}), 400
    except Exception as e:
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@chatbot_bp.route('/api/chatbot/<chatbot_id>', methods=['DELETE'])
@require_auth
def delete_chatbot_user(chatbot_id):
    try:
        bot = chatbot_repo.find_by_id(chatbot_id)
        if not bot:
            return jsonify({"statusCode": 404, "message": "Chatbot not found"}), 404

        success = chatbot_repo.delete_chatbot(chatbot_id)
        if success:
            return jsonify({"statusCode": 200, "message": "Chatbot deleted successfully"})
        return jsonify({"statusCode": 400, "message": "Delete failed"}), 400
    except Exception as e:
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── 3. ADMIN CHATBOT MANAGEMENT & DASHBOARD ENDPOINTS ───────────────────────

@chatbot_bp.route("/api/admin/users", methods=["GET"])
@require_auth
def get_admin_users():
    try:
        if g.user.get("role") != 0:
            return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
        
        page = request.args.get("page", 1, type=int)
        limit = request.args.get("limit", 20, type=int)
        search = request.args.get("search", None)
        active_str = request.args.get("active", None)
        active = active_str.lower() == "true" if active_str is not None else None
        
        users = users_repo.get_users_by_role(role=4, page=page, limit=limit, search=search, active=active)
        total = users_repo.count_users_by_role(role=4, search=search, active=active)
        total_pages = ceil(total / limit) if limit > 0 else 0
        
        for user in users:
            if user.get("account_id"):
                user["chatbot_count"] = chatbot_repo.count_chatbots_by_user(user["account_id"])
                chatbots = chatbot_repo.find_by_account_id(user["account_id"])
                workspace_ids = [cb["workspace_id"] for cb in chatbots if cb.get("workspace_id")]
                
                total_messages = 0
                latest_message = None
                for wid in workspace_ids:
                    total_messages += chat_history_repo.count_messages_by_chatbot(wid)
                    msg_time = chat_history_repo.get_latest_message_by_chatbot(wid)
                    if msg_time and (not latest_message or msg_time > latest_message):
                        latest_message = msg_time
                
                user["total_messages"] = total_messages
                user["latest_message_at"] = latest_message
        
        return jsonify({
            "statusCode": 200,
            "message": "Success",
            "data": {
                "users": users,
                "pagination": {"page": page, "limit": limit, "total": total, "total_pages": total_pages}
            }
        }), 200
    except Exception as e:
        Log.error(f"[Admin API] Error getting users: {e}")
        return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500


@chatbot_bp.route("/api/admin/users/<user_id>", methods=["GET"])
@require_auth
def get_admin_user_detail(user_id):
    try:
        if g.user.get("role") != 0:
            return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
        
        user = users_repo.get_user_with_details(user_id)
        if not user:
            return jsonify({"statusCode": 404, "message": "User not found"}), 404
        
        chatbots = []
        if user.get("account_id"):
            chatbots = chatbot_repo.get_chatbots_by_user(user["account_id"], page=1, limit=100)
        
        message_stats = {"total": 0, "this_week": 0, "this_month": 0}
        if user.get("account_id"):
            user_chatbots = chatbot_repo.find_by_account_id(user["account_id"])
            workspace_ids = [cb["workspace_id"] for cb in user_chatbots if cb.get("workspace_id")]
            for wid in workspace_ids:
                message_stats["total"] += chat_history_repo.count_messages_by_chatbot(wid)
            message_stats["this_week"] = chat_history_repo.get_messages_count_by_period("this_week")
            message_stats["this_month"] = chat_history_repo.get_messages_count_by_period("this_month")
        
        user["chatbots"] = chatbots
        user["message_stats"] = message_stats
        return jsonify({"statusCode": 200, "data": user}), 200
    except Exception as e:
        Log.error(f"[Admin API] Error getting user detail: {e}")
        return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500


@chatbot_bp.route("/api/admin/users/<user_id>/toggle-active", methods=["PUT"])
@require_auth
def toggle_user_active(user_id):
    try:
        if g.user.get("role") != 0:
            return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
        
        result = users_repo.toggle_user_active(user_id)
        if not result:
            return jsonify({"statusCode": 404, "message": "User not found"}), 404
        
        return jsonify({"statusCode": 200, "message": "User status updated successfully", "data": result}), 200
    except Exception as e:
        Log.error(f"[Admin API] Error toggling user active: {e}")
        return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500


@chatbot_bp.route("/api/admin/users/<user_id>/chatbots", methods=["GET"])
@require_auth
def get_user_chatbots(user_id):
    try:
        if g.user.get("role") != 0:
            return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
        
        page = request.args.get("page", 1, type=int)
        limit = request.args.get("limit", 20, type=int)
        user = users_repo.get_user_with_details(user_id)
        if not user or not user.get("account_id"):
            return jsonify({"statusCode": 200, "data": {"chatbots": [], "pagination": {"page": page, "limit": limit, "total": 0, "total_pages": 0}}}), 200
        
        chatbots = chatbot_repo.get_chatbots_by_user(user["account_id"], page=page, limit=limit)
        total = chatbot_repo.count_chatbots_by_user(user["account_id"])
        total_pages = ceil(total / limit) if limit > 0 else 0
        
        for chatbot in chatbots:
            if chatbot.get("workspace_id"):
                chatbot["message_count"] = chat_history_repo.count_messages_by_chatbot(chatbot["workspace_id"])
                chatbot["latest_message_at"] = chat_history_repo.get_latest_message_by_chatbot(chatbot["workspace_id"])
        
        return jsonify({"statusCode": 200, "data": {"chatbots": chatbots, "pagination": {"page": page, "limit": limit, "total": total, "total_pages": total_pages}}}), 200
    except Exception as e:
        Log.error(f"[Admin API] Error getting user chatbots: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@chatbot_bp.route("/api/admin/chatbots", methods=["GET"])
@require_auth
def get_all_chatbots():
    try:
        if g.user.get("role") != 0:
            return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
        
        page = request.args.get("page", 1, type=int)
        limit = request.args.get("limit", 20, type=int)
        search = request.args.get("search", None)
        active_str = request.args.get("active", None)
        active = active_str.lower() == "true" if active_str is not None else None
        
        chatbots = chatbot_repo.get_all_chatbots(page=page, limit=limit, search=search, active=active)
        total = chatbot_repo.count_all_chatbots(search=search, active=active)
        total_pages = ceil(total / limit) if limit > 0 else 0
        
        for chatbot in chatbots:
            if chatbot.get("account_id"):
                user = users_repo.find_one({"account_id": chatbot["account_id"]})
                chatbot["user"] = {"id": str(user["_id"]), "fullname": user.get("fullname", ""), "email": user.get("email", "")} if user else {}
            if chatbot.get("workspace_id"):
                chatbot["message_count"] = chat_history_repo.count_messages_by_chatbot(chatbot["workspace_id"])
                chatbot["latest_message_at"] = chat_history_repo.get_latest_message_by_chatbot(chatbot["workspace_id"])
        
        return jsonify({"statusCode": 200, "data": {"chatbots": chatbots, "pagination": {"page": page, "limit": limit, "total": total, "total_pages": total_pages}}}), 200
    except Exception as e:
        Log.error(f"[Admin API] Error getting all chatbots: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@chatbot_bp.route("/api/admin/chatbots/<chatbot_id>", methods=["GET"])
@require_auth
def get_chatbot_detail_admin(chatbot_id):
    try:
        if g.user.get("role") != 0:
            return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
        
        chatbot = chatbot_repo.get_chatbot_with_details(chatbot_id)
        if not chatbot:
            return jsonify({"statusCode": 404, "message": "Chatbot not found"}), 404
        
        user_info = {}
        if chatbot.get("account_id"):
            user = users_repo.find_one({"account_id": chatbot["account_id"]})
            if user:
                user_info = {"id": str(user["_id"]), "fullname": user.get("fullname", ""), "email": user.get("email", "")}
        
        chatbot["user"] = user_info
        stats = {"total_messages": 0, "today": 0, "this_week": 0, "this_month": 0}
        latest_messages = []
        if chatbot.get("workspace_id"):
            stats["total_messages"] = chat_history_repo.count_messages_by_chatbot(chatbot["workspace_id"])
            stats["today"] = chat_history_repo.get_messages_count_by_period("today")
            stats["this_week"] = chat_history_repo.get_messages_count_by_period("this_week")
            stats["this_month"] = chat_history_repo.get_messages_count_by_period("this_month")
            latest_messages = chat_history_repo.get_messages_by_chatbot(chatbot["workspace_id"], page=1, limit=5)
        
        chatbot["stats"] = stats
        chatbot["latest_messages"] = latest_messages
        return jsonify({"statusCode": 200, "data": chatbot}), 200
    except Exception as e:
        Log.error(f"[Admin API] Error getting chatbot detail: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@chatbot_bp.route("/api/admin/chatbots/<chatbot_id>/messages", methods=["GET"])
@require_auth
def get_chatbot_messages(chatbot_id):
    try:
        if g.user.get("role") != 0:
            return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
        
        page = request.args.get("page", 1, type=int)
        limit = request.args.get("limit", 20, type=int)
        session_id = request.args.get("session_id", None)
        
        chatbot = chatbot_repo.get_chatbot_with_details(chatbot_id)
        if not chatbot or not chatbot.get("workspace_id"):
            return jsonify({"statusCode": 200, "data": {"messages": [], "pagination": {"page": page, "limit": limit, "total": 0, "total_pages": 0}}}), 200
        
        messages = chat_history_repo.get_messages_by_chatbot(chatbot["workspace_id"], page=page, limit=limit, session_id=session_id)
        total = chat_history_repo.count_messages_by_chatbot(chatbot["workspace_id"])
        total_pages = ceil(total / limit) if limit > 0 else 0
        
        return jsonify({"statusCode": 200, "data": {"messages": messages, "pagination": {"page": page, "limit": limit, "total": total, "total_pages": total_pages}}}), 200
    except Exception as e:
        Log.error(f"[Admin API] Error getting chatbot messages: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@chatbot_bp.route("/api/admin/dashboard", methods=["GET"])
@require_auth
def get_admin_dashboard():
    try:
        if g.user.get("role") != 0:
            return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
        
        data = {
            "total_users": users_repo.count_users_by_role(role=4),
            "active_users": users_repo.count_users_by_role(role=4, active=True),
            "total_chatbots": chatbot_repo.get_total_chatbots(),
            "active_chatbots": chatbot_repo.get_total_chatbots(active_only=True),
            "total_messages": chat_history_repo.get_total_messages(),
            "messages_today": chat_history_repo.get_messages_count_by_period("today"),
            "messages_this_week": chat_history_repo.get_messages_count_by_period("this_week"),
            "messages_this_month": chat_history_repo.get_messages_count_by_period("this_month"),
            "latest_active_chatbots": chatbot_repo.get_latest_active_chatbots(limit=10),
            "top_users_by_messages": chat_history_repo.get_top_users_by_messages(limit=10)
        }
        return jsonify({"statusCode": 200, "data": data}), 200
    except Exception as e:
        Log.error(f"[Admin API] Error getting dashboard: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@chatbot_bp.route("/api/admin/stats/messages", methods=["GET"])
@require_auth
def get_message_stats():
    try:
        if g.user.get("role") != 0:
            return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
        
        period = request.args.get("period", "week")
        stats = chat_history_repo.get_message_stats(period=period)
        return jsonify({"statusCode": 200, "data": {"period": period, "data": stats}}), 200
    except Exception as e:
        Log.error(f"[Admin API] Error getting message stats: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@chatbot_bp.route("/api/admin/chatbots/<chatbot_id>/toggle-active", methods=["PUT"])
@require_auth
def toggle_chatbot_active(chatbot_id):
    try:
        if g.user.get("role") != 0:
            return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
        
        result = chatbot_repo.toggle_chatbot_active(chatbot_id)
        if not result:
            return jsonify({"statusCode": 404, "message": "Chatbot not found"}), 404
        
        return jsonify({"statusCode": 200, "message": "Chatbot status updated successfully", "data": result}), 200
    except Exception as e:
        Log.error(f"[Admin API] Error toggling chatbot active: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500
