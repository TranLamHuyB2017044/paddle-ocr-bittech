from flask import Blueprint, request, jsonify
from src.repositories.chatbot_repository import chatbot_repo
from src.repositories.accounts_repository import accounts_repo
from src.services.subscription_service import subscription_service
from src.repositories.chat_history_repository import chat_history_repo
from src.utils.logger import Log
from src.config import PLANS_CONFIG
from src.utils.rate_limit import limiter
import secrets
import re

public_chat_bp = Blueprint('public_chat_bp', __name__)

# State management: Track if we're waiting for contact info
waiting_for_contact = {}  # {session_id: True}
customer_contact_info = {}  # {session_id: {email, phone}}

def extract_contact_info(text):
    """Extract email and phone number from text"""
    info = {}
    
    # Email regex
    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
    emails = re.findall(email_pattern, text)
    if emails:
        info["email"] = emails[0]
    
    # Phone regex (Vietnamese)
    phone_pattern = r'(?:\+?84|0)(?:3[2-9]|5[689]|7[06-9]|8[1-9]|9[0-46-9])[0-9]{7}'
    phones = re.findall(phone_pattern, text)
    if phones:
        info["phone"] = phones[0]
    
    return info

@public_chat_bp.route('/api/public/chatbot/<chatbot_id>', methods=['GET'])
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
            "greeting": chatbot.get("greeting"),
            "workspace_id": str(chatbot["workspace_id"]) if chatbot.get("workspace_id") else None
        }
        return jsonify({"statusCode": 200, "data": formatted})
    except Exception as e:
        Log.error(f"[Public Chatbot Details] Error: {e}")
        return jsonify({"statusCode": 500, "message": "Internal server error"}), 500

@public_chat_bp.route('/api/public/chatbot/<chatbot_id>/chat', methods=['POST'])
@limiter.limit("20 per minute")
def public_chat_with_chatbot(chatbot_id):
    global waiting_for_contact, customer_contact_info
    
    try:
        # 1. Validate public token
        public_token = request.headers.get('x-public-token')
        if not public_token:
            return jsonify({"statusCode": 401, "message": "Missing x-public-token header"}), 401
        
        # 2. Find chatbot
        chatbot = chatbot_repo.find_by_public_token(public_token)
        if not chatbot or str(chatbot["_id"]) != chatbot_id:
            return jsonify({"statusCode": 403, "message": "Invalid chatbot or token"}), 403
        
        # 3. Get account
        account = accounts_repo.find_by_id(chatbot["account_id"])
        if not account:
            return jsonify({"statusCode": 404, "message": "Account not found"}), 404
        
        # 4. Check quota
        plan_key = account.get("plan", 0)
        plan_cfg = PLANS_CONFIG.get(plan_key, {})
        if not plan_cfg.get("is_unlimited", False):
            max_requests = plan_cfg.get("max_requests_per_month", 0)
            used_requests = account.get("used_requests", 0)
            if used_requests + 1 > max_requests:
                return jsonify({
                    "statusCode": 403, 
                    "message": f"Quota exceeded: {used_requests}/{max_requests}"
                }), 403
        
        # 5. Get user message and session_id
        data = request.json or {}
        message = data.get("message")
        session_id = data.get("session_id") or secrets.token_urlsafe(16)
        
        if not message:
            return jsonify({"statusCode": 400, "message": "Message is required"}), 400
        
        result = {"answer": "", "provider": "echo"}
        
        is_contact_info_reply = False
        # 6. Check if we're waiting for contact info
        if session_id in waiting_for_contact and waiting_for_contact[session_id]:
            is_contact_info_reply = True
            # Extract contact info
            info = extract_contact_info(message)
            customer_contact_info[session_id] = info
            waiting_for_contact[session_id] = False
            
            # Confirmation message
            confirmation_text = "Cảm ơn bạn! Nhân viên sẽ liên hệ lại sớm nhất."
            if info.get("email"):
                confirmation_text += f"\nEmail: {info['email']}"
            if info.get("phone"):
                confirmation_text += f"\nSĐT: {info['phone']}"
            
            result["answer"] = confirmation_text
            
            # Send telegram notification with contact info
            if chatbot.get("telegram_bot_token") and chatbot.get("telegram_chat_id"):
                try:
                    from src.services.telegram_service import send_telegram_message, format_customer_question_notification
                    last_question = "Khách hàng đã để lại thông tin liên hệ"
                    full_message = format_customer_question_notification(last_question, chatbot.get("name", "Chatbot"))
                    full_message += f"\n\n🔑 Session ID: {session_id}"
                    if info:
                        full_message += "\n\n📞 Thông tin liên hệ:"
                        if info.get("email"):
                            full_message += f"\nEmail: {info['email']}"
                        if info.get("phone"):
                            full_message += f"\nSĐT: {info['phone']}"
                    send_telegram_message(
                        chatbot["telegram_bot_token"],
                        chatbot["telegram_chat_id"],
                        full_message
                    )
                except Exception as e:
                    Log.error(f"[Public Chat] Lỗi khi gửi thông báo Telegram: {e}")
        
        else:
            # 7. Normal chat flow
            if chatbot.get("workspace_id"):
                from src.rag.rag_service import rag_service
                result = rag_service.chat_store(
                    question=message,
                    workspace_id=str(chatbot["workspace_id"]),
                    telegram_bot_token=None,  # Disable auto-notify, let public route handle it
                    telegram_chat_id=None,
                    chatbot_name=chatbot.get("name", "Chatbot")
                )
                
                # Check if we need to ask for contact info
                no_info_keywords = ["không có thông tin", "không tìm thấy", "không biết", "sẽ liên hệ", "liên hệ lại"]
                is_no_info = any(keyword.lower() in result["answer"].lower() for keyword in no_info_keywords)
                
                if is_no_info:
                    # Ask for contact info
                    result["answer"] += "\n\nVui lòng để lại email hoặc số điện thoại để nhân viên hỗ trợ chi tiết hơn nhé!"
                    waiting_for_contact[session_id] = True
                    
                    # Send initial telegram notification with question
                    if chatbot.get("telegram_bot_token") and chatbot.get("telegram_chat_id"):
                        try:
                            from src.services.telegram_service import send_telegram_message, format_customer_question_notification
                            full_message = format_customer_question_notification(message, chatbot.get("name", "Chatbot"))
                            full_message += f"\n\n🔑 Session ID: {session_id}"
                            send_telegram_message(
                                chatbot["telegram_bot_token"],
                                chatbot["telegram_chat_id"],
                                full_message
                            )
                        except Exception as e:
                            Log.error(f"[Public Chat] Lỗi khi gửi thông báo Telegram: {e}")
            
            else:
                result["answer"] = f"Cảm ơn bạn đã hỏi: {message}"
        
        # 8. Increment quota only if it's not a contact info reply
        if not is_contact_info_reply:
            accounts_repo.increment_usage(chatbot["account_id"])
        
        # 9. Save chat history
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
        
        return jsonify({"statusCode": 200, "data": {**result, "sessionId": session_id}})
        
    except Exception as e:
        Log.error(f"[Public Chat] Error: {e}")
        return jsonify({"statusCode": 500, "message": "Internal server error"}), 500

@public_chat_bp.route('/api/public/chatbot/<chatbot_id>/suggest', methods=['GET'])
@limiter.limit("100 per minute")
def get_public_chatbot_suggestions(chatbot_id):
    try:
        public_token = request.headers.get('x-public-token')
        if not public_token:
            return jsonify({"statusCode": 401, "message": "Missing x-public-token header"}), 401
        
        chatbot = chatbot_repo.find_by_public_token(public_token)
        if not chatbot or str(chatbot["_id"]) != chatbot_id:
            return jsonify({"statusCode": 403, "message": "Invalid chatbot or token"}), 403
        
        # If no workspace, return empty suggestions
        if not chatbot.get("workspace_id"):
            return jsonify({"statusCode": 200, "data": {"suggestions": []}})
        
        # Get suggestions from rag service
        from src.rag.rag_service import rag_service
        suggestions = rag_service.suggest_questions(str(chatbot["workspace_id"]))
        
        return jsonify({"statusCode": 200, "data": {"suggestions": suggestions}})
    except Exception as e:
        Log.error(f"[Public Chatbot Suggestions] Error: {e}")
        return jsonify({"statusCode": 500, "message": "Internal server error"}), 500

@public_chat_bp.route('/chatbot-embed.js', methods=['GET'])
@limiter.limit("200 per minute")
def get_embed_script():
    try:
        import os
        from flask import send_from_directory
        # Find absolute path of project root - works in both dev and Docker
        current_dir = os.path.dirname(os.path.abspath(__file__)) # src/api
        src_dir = os.path.dirname(current_dir) # src
        root_dir = os.path.dirname(src_dir) # root (where app.py is)
        public_dir = os.path.join(root_dir, 'public')
        file_path = os.path.join(public_dir, 'chatbot-embed.js')
        
        Log.info(f"[Embed Script] Looking for file at: {file_path}")
        Log.info(f"[Embed Script] Public dir: {public_dir}")
        Log.info(f"[Embed Script] Root dir: {root_dir}")
        
        if os.path.exists(file_path):
            return send_from_directory(public_dir, 'chatbot-embed.js', mimetype='application/javascript')
        else:
            Log.error(f"[Embed Script] File not found at: {file_path}")
            return "Script not found", 404
    except Exception as e:
        Log.error(f"[Embed Script] Error serving script: {e}")
        import traceback
        Log.error(traceback.format_exc())
        return "Script not found", 404
