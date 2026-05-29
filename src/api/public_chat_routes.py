from flask import Blueprint, request, jsonify
from src.repositories.chatbot_repository import chatbot_repo
from src.repositories.accounts_repository import accounts_repo
from src.services.subscription_service import subscription_service
from src.repositories.chat_history_repository import chat_history_repo
from src.utils.logger import Log
from src.config import PLANS_CONFIG

public_chat_bp = Blueprint('public_chat_bp', __name__)

@public_chat_bp.route('/api/public/chatbot/<chatbot_id>/chat', methods=['POST'])
def public_chat_with_chatbot(chatbot_id):
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
        
        # 5. Get user message
        data = request.json or {}
        message = data.get("message")
        if not message:
            return jsonify({"statusCode": 400, "message": "Message is required"}), 400
        
        # 6. Process chat (RAG if workspace exists)
        result = {"answer": f"Cảm ơn bạn đã hỏi: {message}", "sources": [], "provider": "echo"}
        
        if chatbot.get("workspace_id"):
            from src.rag.rag_service import rag_service
            result = rag_service.query(message, str(chatbot["workspace_id"]))
        
        # 7. Increment quota
        accounts_repo.increment_usage(chatbot["account_id"])
        
        # 8. Save chat history (anonymous)
        chat_history_repo.save_message(
            workspace_id=chatbot.get("workspace_id"),
            user_id="anonymous",
            question=message,
            answer=result["answer"],
            sources=result.get("sources"),
            provider=result.get("provider")
        )
        
        return jsonify({"statusCode": 200, "data": result})
        
    except Exception as e:
        Log.error(f"[Public Chat] Error: {e}")
        return jsonify({"statusCode": 500, "message": "Internal server error"}), 500

@public_chat_bp.route('/chatbot-embed.js', methods=['GET'])
def get_embed_script():
    try:
        import os
        from flask import send_from_directory
        # Find absolute path of project root
        current_dir = os.path.dirname(os.path.abspath(__file__)) # src/api
        src_dir = os.path.dirname(current_dir) # src
        root_dir = os.path.dirname(src_dir) # root
        public_dir = os.path.join(root_dir, 'public')
        return send_from_directory(public_dir, 'chatbot-embed.js', mimetype='application/javascript')
    except Exception as e:
        Log.error(f"[Embed Script] Error serving script: {e}")
        return "Script not found", 404
