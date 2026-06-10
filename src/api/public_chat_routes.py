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
customer_contact_info = {}  # {session_id: {name, phone}}
last_question_before_contact = {}  # {session_id: original_question}

def extract_contact_info(text):
    """Extract name and phone number with flexible format: Tôi tên là [tên] - sđt [số điện thoại]"""
    info = {}
    # Flexible regex pattern:
    # - Case insensitive (handled by flags)
    # - Allow optional spaces, dashes, dots, commas as separators
    # - Support: sđt, sdt, so dien thoai, sdt, SĐT, etc.
    # - Phone supports: 0912345678 (10 số), +84912345678, with spaces/dots/dashes
    # - Note: We prefer 10-digit phone numbers
    pattern = r'tôi tên là\s+(.+?)\s*(?:-|,|;)?\s*(?:sđt|sdt|số điện thoại|so dien thoai)\s*[:\-]?\s*((?:\+?84|0)(?:3[2-9]|5[2689]|7[06-9]|8[1-9]|9[0-46-9])[-.\s]?[0-9]{3}[-.\s]?[0-9]{4})'
    
    match = re.search(pattern, text, flags=re.IGNORECASE)
    
    if match:
        name = match.group(1).strip()
        phone = match.group(2).strip()
        
        # Normalize phone number
        normalized_phone = re.sub(r'[-.\s]', '', phone)
        
        # Validate name (at least 2 characters)
        if len(name) >= 2:
            info["name"] = name
        info["phone"] = normalized_phone
    
    Log.info(f"[extract_contact_info] Input: {text} → Output: {info}")
    
    return info

def analyze_contact_info_error(text):
    """Analyze what's wrong with the contact info input"""
    text_lower = text.lower()
    
    # Check if has "tôi tên là"
    has_name_prefix = "tôi tên là" in text_lower
    
    # Check if has phone number keyword
    has_phone_keyword = any(keyword in text_lower for keyword in ["sđt", "sdt", "số điện thoại", "so dien thoai"])
    
    # Try to extract potential name
    potential_name = None
    if has_name_prefix:
        name_match = re.search(r'tôi tên là\s+(.+?)(?:\s*(?:-|,|;|:|$))', text, flags=re.IGNORECASE)
        if name_match:
            potential_name = name_match.group(1).strip()
    
    # Try to extract potential phone number
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
        # Check if phone number is valid
        normalized_phone = re.sub(r'[-.\s]', '', potential_phone)
        if len(normalized_phone) not in [9, 10] and not normalized_phone.startswith('+84') and len(normalized_phone) not in [11, 12]:
            errors.append("Số điện thoại phải có 9-10 số (hoặc 11-12 số nếu có +84)")
        elif not re.match(r'(?:\+?84|0)(?:3[2-9]|5[2689]|7[06-9]|8[1-9]|9[0-46-9])', normalized_phone):
            errors.append("Số điện thoại không đúng định dạng đầu số Việt Nam")
    
    return errors

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
            "workspace_id": str(chatbot["workspace_id"]) if chatbot.get("workspace_id") else None,
            "workflow_webhook_url": chatbot.get("workflow_webhook_url")
        }
        return jsonify({"statusCode": 200, "data": formatted})
    except Exception as e:
        Log.error(f"[Public Chatbot Details] Error: {e}")
        return jsonify({"statusCode": 500, "message": "Internal server error"}), 500

@public_chat_bp.route('/api/public/chatbot/<chatbot_id>/chat', methods=['POST'])
@limiter.limit("50 per minute")
def public_chat_with_chatbot(chatbot_id):
    global waiting_for_contact, customer_contact_info, last_question_before_contact
    
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
        
        # 5. Get user message and session_id (support both session_id and sessionId)
        data = request.json or {}
        message = data.get("message")
        session_id = data.get("session_id") or data.get("sessionId") or secrets.token_urlsafe(16)
        
        if not message:
            return jsonify({"statusCode": 400, "message": "Message is required"}), 400
        
        Log.info(f"[Public Chat] Received message: '{message}' with session_id: '{session_id}'")
        
        result = {"answer": "", "provider": "echo"}
        
        is_contact_info_reply = False
        # 6. Check if we're waiting for contact info FIRST!
        Log.info(f"[Public Chat] Checking session {session_id} - waiting_for_contact: {session_id in waiting_for_contact}")
        if session_id in waiting_for_contact and waiting_for_contact[session_id]:
            # Extract contact info
            info = extract_contact_info(message)
            Log.info(f"[Public Chat] Extracted info: {info}")
            
            # Check if we have both name AND phone
            if info.get("name") and info.get("phone"):
                # Got enough info, proceed
                is_contact_info_reply = True
                customer_contact_info[session_id] = info
                waiting_for_contact[session_id] = False
                
                # Confirmation message
                confirmation_text = "Tôi đã liên hệ nhân viên, họ sẽ liên hệ lại sau!"
                confirmation_text += f"\nHọ tên: {info['name']}"
                confirmation_text += f"\nSĐT: {info['phone']}"
                
                result["answer"] = confirmation_text
                
                # Send telegram notification ONLY NOW with contact info and last question
                Log.info(f"[Public Chat] Telegram config - token: {bool(chatbot.get('telegram_bot_token'))}, chat_id: {bool(chatbot.get('telegram_chat_id'))}")
                if chatbot.get("telegram_bot_token") and chatbot.get("telegram_chat_id"):
                    try:
                        from src.services.telegram_service import send_telegram_message, format_customer_question_notification
                        # Get the original question
                        original_question = last_question_before_contact.get(session_id, "Không có câu hỏi trước đó")
                        full_message = format_customer_question_notification(original_question, chatbot.get("name", "Chatbot"))
                        full_message += f"\n\n🔑 Session ID: {session_id}"
                        full_message += "\n\n📞 Thông tin liên hệ:"
                        full_message += f"\nHọ tên: {info['name']}"
                        full_message += f"\nSĐT: {info['phone']}"
                        Log.info(f"[Public Chat] Sending Telegram message: {full_message}")
                        send_result = send_telegram_message(
                            chatbot["telegram_bot_token"],
                            chatbot["telegram_chat_id"],
                            full_message
                        )
                        Log.info(f"[Public Chat] Telegram send result: {send_result}")
                    except Exception as e:
                        Log.error(f"[Public Chat] Lỗi khi gửi thông báo Telegram: {e}")
                        import traceback
                        Log.error(traceback.format_exc())
            else:
                # No valid format - Analyze error and show specific feedback
                errors = analyze_contact_info_error(message)
                if errors:
                    result["answer"] = "Thông tin chưa đúng định dạng! Lỗi:\n- " + "\n- ".join(errors)
                else:
                    result["answer"] = "Vui lòng cung cấp thông tin theo định dạng để liên hệ nhân viên: Tôi tên là [tên] - sđt [số điện thoại]"
                result["answer"] += "\n\nVí dụ đúng: Tôi tên là Nguyễn Văn A - sđt 0912345678"
        
        else:
            # 7. Normal chat flow
            # First check hard-coded answer for "bạn là ai"
            question_lower = message.lower().strip()
            if any(q in question_lower for q in ["bạn là ai", "bạn là ai?", "bạn là ai ?"]):
                result["answer"] = "Tôi là chatbot chăm sóc khách hàng!"
            else:
                # Then check if user is asking to contact staff directly
                contact_request_keywords = ["liên hệ nhân viên", "hãy liên hệ", "nhân viên hỗ trợ", "liên hệ với nhân viên", "gọi nhân viên"]
                is_contact_request = any(keyword.lower() in message.lower() for keyword in contact_request_keywords)
                
                if chatbot.get("workspace_id") and not is_contact_request:
                    from src.rag.rag_service import rag_service
                    result = rag_service.chat_store(
                        question=message,
                        workspace_id=str(chatbot["workspace_id"]),
                        telegram_bot_token=None,  # Disable auto-notify, let public route handle it
                        telegram_chat_id=None,
                        chatbot_name=chatbot.get("name", "Chatbot")
                    )
                    
                    # Check if we need to ask for contact info
                    no_info_keywords = ["không có thông tin", "không tìm thấy", "không biết"]
                    is_no_info = any(keyword.lower() in result["answer"].lower() for keyword in no_info_keywords)
                    
                    if is_no_info:
                        # Ask for contact info with clear format guide
                        result["answer"] += "\n\nVui lòng cung cấp thông tin theo định dạng để liên hệ nhân viên: Tôi tên là [tên] - sđt [số điện thoại]"
                        waiting_for_contact[session_id] = True
                        # Save the original question
                        last_question_before_contact[session_id] = message
                else:
                    # Either no workspace OR user is asking to contact staff directly
                    if is_contact_request:
                        result["answer"] = "Vui lòng cung cấp thông tin theo định dạng để liên hệ nhân viên: Tôi tên là [tên] - sđt [số điện thoại]"
                        waiting_for_contact[session_id] = True
                        last_question_before_contact[session_id] = message
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
        
        return jsonify({"statusCode": 200, "data": {**result, "sessionId": session_id, "waitingForContact": waiting_for_contact.get(session_id, False)}})
        
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
        current_dir = os.path.dirname(os.path.abspath(__file__))
        src_dir = os.path.dirname(current_dir)
        root_dir = os.path.dirname(src_dir)
        public_dir = os.path.join(root_dir, 'public')
        file_path = os.path.join(public_dir, 'chatbot-embed.js')
        
        Log.info(f"[Embed Script] Looking for file at: {file_path}")
        
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


@public_chat_bp.route('/chatbot-embed-n8n.js', methods=['GET'])
@limiter.limit("200 per minute")
def get_embed_script_n8n():
    try:
        import os
        from flask import send_from_directory
        current_dir = os.path.dirname(os.path.abspath(__file__))
        src_dir = os.path.dirname(current_dir)
        root_dir = os.path.dirname(src_dir)
        public_dir = os.path.join(root_dir, 'public')
        file_path = os.path.join(public_dir, 'chatbot-embed-n8n.js')
        
        Log.info(f"[Embed Script n8n] Looking for file at: {file_path}")
        
        if os.path.exists(file_path):
            return send_from_directory(public_dir, 'chatbot-embed-n8n.js', mimetype='application/javascript')
        else:
            Log.error(f"[Embed Script n8n] File not found at: {file_path}")
            return "Script not found", 404
    except Exception as e:
        Log.error(f"[Embed Script n8n] Error serving script: {e}")
        import traceback
        Log.error(traceback.format_exc())
        return "Script not found", 404
