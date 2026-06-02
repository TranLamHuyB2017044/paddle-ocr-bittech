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
    """Extract name and/or phone number from text, with better accuracy, and check if it's just a question/non-contact message"""
    info = {}
    text_lower = text.lower()
    
    # First, check if this is likely a question or non-contact message
    question_indicators = [
        "?", "là gì", "như thế nào", "thế nào", " làm sao", "có không", "được không", 
        "xin hỏi", "hỏi", "nào", "tại sao", "vì sao", "bạn có", "tôi muốn", "tôi cần",
        "cám ơn", "cảm ơn", "ok", "okay", "được rồi", "được", "không", "có", "được không",
        "ạ", "ơi", "à", "ôi", "nha"
    ]
    
    # Also check for question mark
    has_question_mark = "?" in text
    has_question_indicator = any(ind in text_lower for ind in question_indicators)
    
    # First, clean the text by removing any markdown or special characters that might interfere
    cleaned_text = re.sub(r'[*_`~]', '', text)
    
    # Phone regex (Vietnamese) - more robust
    # Covers:
    # - 0912345678
    # - +84912345678
    # - 091 234 5678 (with spaces)
    # - 091.234.5678 (with dots)
    # - 091-234-5678 (with dashes)
    phone_pattern = r'(?:\+?84|0)(?:3[2-9]|5[2689]|7[06-9]|8[1-9]|9[0-46-9])[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}'
    phones = re.findall(phone_pattern, cleaned_text)
    
    if phones:
        # Normalize the phone number (remove spaces, dots, dashes)
        normalized_phone = re.sub(r'[-.\s]', '', phones[0])
        info["phone"] = normalized_phone
    
    # Name extraction - improved
    # 1. Remove any phone numbers first
    text_without_phone = cleaned_text
    if phones:
        text_without_phone = re.sub(re.escape(phones[0]), '', text_without_phone, flags=re.IGNORECASE).strip()
    
    # 2. Remove common prefixes and keywords
    prefixes_to_remove = [
        r'^(tên|họ tên|tên tôi là|tôi tên là|mynameis|name:|tôi là)\s*',
        r'^(sdt|số điện thoại|phone|điện thoại|số đt|số máy|liên hệ):?\s*',
        r'\s*(sdt|số điện thoại|phone|điện thoại|số đt|số máy|liên hệ):?\s*.*$'
    ]
    
    name_candidate = text_without_phone
    for pattern in prefixes_to_remove:
        name_candidate = re.sub(pattern, '', name_candidate, flags=re.IGNORECASE)
    
    # 3. Also handle cases where name is before phone
    if phones and not name_candidate.strip():
        # Try to get text before phone
        phone_index = text.lower().find(phones[0].lower())
        if phone_index > 0:
            name_candidate = text[:phone_index].strip()
            # Clean it again
            for pattern in prefixes_to_remove:
                name_candidate = re.sub(pattern, '', name_candidate, flags=re.IGNORECASE)
    
    name_candidate = name_candidate.strip()
    
    # 4. Validate the name - should have at least 2 characters and not be just numbers
    if len(name_candidate) >= 2 and not re.fullmatch(r'[0-9\s]+', name_candidate):
        # Only accept as name only if it doesn't look like a question/non-contact
        if not (has_question_mark or has_question_indicator):
            info["name"] = name_candidate
    
    # Now, decide if this is likely contact info or not
    likely_contact = (
        info.get("phone") is not None or 
        (info.get("name") and len(info.get("name")) >= 2)
    )
    
    # Even if it has question indicators, if it has clear contact info, still accept it
    if has_question_indicator and not likely_contact:
        # If it's a question without clear contact info, treat as non-contact
        info = {}
    
    # Log what we found
    Log.info(f"[extract_contact_info] Input: {text} → Output: {info}, Likely contact: {likely_contact}, Has question: {has_question_mark or has_question_indicator}")
    
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
        
        # 5. Get user message and session_id
        data = request.json or {}
        message = data.get("message")
        session_id = data.get("session_id") or secrets.token_urlsafe(16)
        
        if not message:
            return jsonify({"statusCode": 400, "message": "Message is required"}), 400
        
        result = {"answer": "", "provider": "echo"}
        
        is_contact_info_reply = False
        # 6. Check if we're waiting for contact info
        Log.info(f"[Public Chat] Checking session {session_id} - waiting_for_contact: {session_id in waiting_for_contact}")
        if session_id in waiting_for_contact and waiting_for_contact[session_id]:
            # Extract contact info
            info = extract_contact_info(message)
            Log.info(f"[Public Chat] Extracted info: {info}")
            
            # Check if we have either name OR phone
            if info.get("name") or info.get("phone"):
                # Got enough info, proceed
                is_contact_info_reply = True
                customer_contact_info[session_id] = info
                waiting_for_contact[session_id] = False
                
                # Confirmation message
                confirmation_text = "Tôi đã liên hệ nhân viên, họ sẽ liên hệ lại sau. Nếu có bất kỳ câu hỏi nào khác hãy hỏi tôi!"
                if info.get("name"):
                    confirmation_text += f"\nHọ tên: {info['name']}"
                if info.get("phone"):
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
                        if info:
                            full_message += "\n\n📞 Thông tin liên hệ:"
                            if info.get("name"):
                                full_message += f"\nHọ tên: {info['name']}"
                            if info.get("phone"):
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
                # No contact info found - check if it's a question/other message
                # First, try to answer it normally if possible
                if chatbot.get("workspace_id"):
                    from src.rag.rag_service import rag_service
                    result = rag_service.chat_store(
                        question=message,
                        workspace_id=str(chatbot["workspace_id"]),
                        telegram_bot_token=None,
                        telegram_chat_id=None,
                        chatbot_name=chatbot.get("name", "Chatbot")
                    )
                    # Append reminder about contact info
                    result["answer"] += "\n\nVui lòng cung cấp họ tên hoặc số điện thoại để nhân viên hỗ trợ chi tiết nhé!"
                else:
                    result["answer"] = "Vui lòng cung cấp họ tên hoặc số điện thoại để nhân viên hỗ trợ nhé!"
        
        else:
            # 7. Normal chat flow
            # First check if user is asking to contact staff directly
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
                    # Ask for contact info (name and phone)
                    result["answer"] += "\n\nVui lòng để lại họ tên và số điện thoại để nhân viên hỗ trợ chi tiết hơn nhé!"
                    waiting_for_contact[session_id] = True
                    # Save the original question
                    last_question_before_contact[session_id] = message
            else:
                # Either no workspace OR user is asking to contact staff directly
                if is_contact_request:
                    result["answer"] = "Vui lòng để lại họ tên và số điện thoại để nhân viên hỗ trợ chi tiết hơn nhé!"
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
