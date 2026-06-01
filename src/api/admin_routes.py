"""
Admin API Routes
Routes for managing users and chatbots
"""
from flask import request, jsonify, g
from src.utils.auth_middleware import require_auth
from src.utils.logger import Log
from src.repositories.users_repository import users_repo
from src.repositories.chatbot_repository import chatbot_repo
from src.repositories.chat_history_repository import chat_history_repo
from math import ceil


def register_admin_routes(app):
    """
    Register admin routes to Flask app
    """
    
    @app.route("/api/admin/users", methods=["GET"])
    @require_auth
    def get_admin_users():
        """Get list of users with role 4"""
        try:
            # Check if user is admin
            if g.user.get("role") != 0:
                return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
            
            # Parse query params
            page = request.args.get("page", 1, type=int)
            limit = request.args.get("limit", 20, type=int)
            search = request.args.get("search", None)
            active_str = request.args.get("active", None)
            active = None
            if active_str is not None:
                active = active_str.lower() == "true"
            
            # Get users
            users = users_repo.get_users_by_role(
                role=4,
                page=page,
                limit=limit,
                search=search,
                active=active
            )
            total = users_repo.count_users_by_role(role=4, search=search, active=active)
            total_pages = ceil(total / limit) if limit > 0 else 0
            
            # Enrich user data with chatbot count and message info
            for user in users:
                if user.get("account_id"):
                    # Get chatbot count
                    user["chatbot_count"] = chatbot_repo.count_chatbots_by_user(user["account_id"])
                    
                    # Get total messages and latest message
                    chatbots = chatbot_repo.find_by_account_id(user["account_id"])
                    workspace_ids = [cb["workspace_id"] for cb in chatbots if cb.get("workspace_id")]
                    
                    total_messages = 0
                    latest_message = None
                    for wid in workspace_ids:
                        total_messages += chat_history_repo.count_messages_by_chatbot(wid)
                        msg_time = chat_history_repo.get_latest_message_by_chatbot(wid)
                        if msg_time:
                            if not latest_message or msg_time > latest_message:
                                latest_message = msg_time
                    
                    user["total_messages"] = total_messages
                    user["latest_message_at"] = latest_message
            
            return jsonify({
                "statusCode": 200,
                "message": "Success",
                "data": {
                    "users": users,
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total": total,
                        "total_pages": total_pages
                    }
                }
            }), 200
        except Exception as e:
            Log.error(f"[Admin API] Error getting users: {e}")
            return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500
    
    @app.route("/api/admin/users/<user_id>", methods=["GET"])
    @require_auth
    def get_admin_user_detail(user_id):
        """Get user detail by ID"""
        try:
            # Check if user is admin
            if g.user.get("role") != 0:
                return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
            
            user = users_repo.get_user_with_details(user_id)
            if not user:
                return jsonify({"statusCode": 404, "message": "User not found"}), 404
            
            # Get user's chatbots
            chatbots = []
            if user.get("account_id"):
                chatbots = chatbot_repo.get_chatbots_by_user(user["account_id"], page=1, limit=100)
            
            # Get message stats
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
            
            return jsonify({
                "statusCode": 200,
                "message": "Success",
                "data": user
            }), 200
        except Exception as e:
            Log.error(f"[Admin API] Error getting user detail: {e}")
            return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500
    
    @app.route("/api/admin/users/<user_id>/toggle-active", methods=["PUT"])
    @require_auth
    def toggle_user_active(user_id):
        """Toggle user active status"""
        try:
            # Check if user is admin
            if g.user.get("role") != 0:
                return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
            
            result = users_repo.toggle_user_active(user_id)
            if not result:
                return jsonify({"statusCode": 404, "message": "User not found"}), 404
            
            return jsonify({
                "statusCode": 200,
                "message": "User status updated successfully",
                "data": result
            }), 200
        except Exception as e:
            Log.error(f"[Admin API] Error toggling user active: {e}")
            return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500
    
    @app.route("/api/admin/users/<user_id>/chatbots", methods=["GET"])
    @require_auth
    def get_user_chatbots(user_id):
        """Get chatbots of a specific user"""
        try:
            if g.user.get("role") != 0:
                return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
            
            page = request.args.get("page", 1, type=int)
            limit = request.args.get("limit", 20, type=int)
            
            user = users_repo.get_user_with_details(user_id)
            if not user:
                return jsonify({"statusCode": 404, "message": "User not found"}), 404
            
            if not user.get("account_id"):
                return jsonify({
                    "statusCode": 200,
                    "message": "Success",
                    "data": {"chatbots": [], "pagination": {"page": page, "limit": limit, "total": 0, "total_pages": 0}}
                }), 200
            
            chatbots = chatbot_repo.get_chatbots_by_user(user["account_id"], page=page, limit=limit)
            total = chatbot_repo.count_chatbots_by_user(user["account_id"])
            total_pages = ceil(total / limit) if limit > 0 else 0
            
            # Enrich chatbots with message count and latest message
            for chatbot in chatbots:
                if chatbot.get("workspace_id"):
                    chatbot["message_count"] = chat_history_repo.count_messages_by_chatbot(chatbot["workspace_id"])
                    chatbot["latest_message_at"] = chat_history_repo.get_latest_message_by_chatbot(chatbot["workspace_id"])
                else:
                    chatbot["message_count"] = 0
                    chatbot["latest_message_at"] = None
            
            return jsonify({
                "statusCode": 200,
                "message": "Success",
                "data": {
                    "chatbots": chatbots,
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total": total,
                        "total_pages": total_pages
                    }
                }
            }), 200
        except Exception as e:
            Log.error(f"[Admin API] Error getting user chatbots: {e}")
            return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500
    
    @app.route("/api/admin/chatbots", methods=["GET"])
    @require_auth
    def get_all_chatbots():
        """Get all chatbots for admin management"""
        try:
            if g.user.get("role") != 0:
                return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
            
            # Parse query params
            page = request.args.get("page", 1, type=int)
            limit = request.args.get("limit", 20, type=int)
            search = request.args.get("search", None)
            active_str = request.args.get("active", None)
            active = None
            if active_str is not None:
                active = active_str.lower() == "true"
            
            # Get chatbots
            chatbots = chatbot_repo.get_all_chatbots(
                page=page,
                limit=limit,
                search=search,
                active=active
            )
            total = chatbot_repo.count_all_chatbots(search=search, active=active)
            total_pages = ceil(total / limit) if limit > 0 else 0
            
            # Enrich chatbots with user info, message count and latest message
            for chatbot in chatbots:
                # Get user info
                if chatbot.get("account_id"):
                    user = users_repo.find_one({"account_id": chatbot["account_id"]})
                    if user:
                        chatbot["user"] = {
                            "id": str(user["_id"]),
                            "fullname": user.get("fullname", ""),
                            "email": user.get("email", "")
                        }
                    else:
                        chatbot["user"] = {}
                else:
                    chatbot["user"] = {}
                
                # Get message count and latest message
                if chatbot.get("workspace_id"):
                    chatbot["message_count"] = chat_history_repo.count_messages_by_chatbot(chatbot["workspace_id"])
                    chatbot["latest_message_at"] = chat_history_repo.get_latest_message_by_chatbot(chatbot["workspace_id"])
                else:
                    chatbot["message_count"] = 0
                    chatbot["latest_message_at"] = None
            
            return jsonify({
                "statusCode": 200,
                "message": "Success",
                "data": {
                    "chatbots": chatbots,
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total": total,
                        "total_pages": total_pages
                    }
                }
            }), 200
        except Exception as e:
            Log.error(f"[Admin API] Error getting all chatbots: {e}")
            return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500
    
    @app.route("/api/admin/chatbots/<chatbot_id>", methods=["GET"])
    @require_auth
    def get_chatbot_detail(chatbot_id):
        """Get chatbot detail by ID"""
        try:
            if g.user.get("role") != 0:
                return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
            
            chatbot = chatbot_repo.get_chatbot_with_details(chatbot_id)
            if not chatbot:
                return jsonify({"statusCode": 404, "message": "Chatbot not found"}), 404
            
            # Get user info for chatbot
            user_info = {}
            if chatbot.get("account_id"):
                user = users_repo.find_one({"account_id": chatbot["account_id"]})
                if user:
                    user_info = {
                        "id": str(user["_id"]),
                        "fullname": user.get("fullname", ""),
                        "email": user.get("email", "")
                    }
            
            chatbot["user"] = user_info
            
            # Get stats
            stats = {
                "total_messages": 0,
                "today": 0,
                "this_week": 0,
                "this_month": 0
            }
            latest_messages = []
            if chatbot.get("workspace_id"):
                stats["total_messages"] = chat_history_repo.count_messages_by_chatbot(chatbot["workspace_id"])
                stats["today"] = chat_history_repo.get_messages_count_by_period("today")
                stats["this_week"] = chat_history_repo.get_messages_count_by_period("this_week")
                stats["this_month"] = chat_history_repo.get_messages_count_by_period("this_month")
                latest_messages = chat_history_repo.get_messages_by_chatbot(chatbot["workspace_id"], page=1, limit=5)
            
            chatbot["stats"] = stats
            chatbot["latest_messages"] = latest_messages
            
            return jsonify({
                "statusCode": 200,
                "message": "Success",
                "data": chatbot
            }), 200
        except Exception as e:
            Log.error(f"[Admin API] Error getting chatbot detail: {e}")
            return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500
    
    @app.route("/api/admin/chatbots/<chatbot_id>/messages", methods=["GET"])
    @require_auth
    def get_chatbot_messages(chatbot_id):
        """Get chatbot messages history"""
        try:
            if g.user.get("role") != 0:
                return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
            
            page = request.args.get("page", 1, type=int)
            limit = request.args.get("limit", 20, type=int)
            session_id = request.args.get("session_id", None)
            
            chatbot = chatbot_repo.get_chatbot_with_details(chatbot_id)
            if not chatbot:
                return jsonify({"statusCode": 404, "message": "Chatbot not found"}), 404
            
            if not chatbot.get("workspace_id"):
                return jsonify({
                    "statusCode": 200,
                    "message": "Success",
                    "data": {"messages": [], "pagination": {"page": page, "limit": limit, "total": 0, "total_pages": 0}}
                }), 200
            
            messages = chat_history_repo.get_messages_by_chatbot(
                chatbot["workspace_id"],
                page=page,
                limit=limit,
                session_id=session_id
            )
            total = chat_history_repo.count_messages_by_chatbot(chatbot["workspace_id"])
            total_pages = ceil(total / limit) if limit > 0 else 0
            
            return jsonify({
                "statusCode": 200,
                "message": "Success",
                "data": {
                    "messages": messages,
                    "pagination": {
                        "page": page,
                        "limit": limit,
                        "total": total,
                        "total_pages": total_pages
                    }
                }
            }), 200
        except Exception as e:
            Log.error(f"[Admin API] Error getting chatbot messages: {e}")
            return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500
    
    @app.route("/api/admin/dashboard", methods=["GET"])
    @require_auth
    def get_admin_dashboard():
        """Get dashboard statistics"""
        try:
            if g.user.get("role") != 0:
                return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
            
            total_users = users_repo.count_users_by_role(role=4)
            active_users = users_repo.count_users_by_role(role=4, active=True)
            total_chatbots = chatbot_repo.get_total_chatbots()
            active_chatbots = chatbot_repo.get_total_chatbots(active_only=True)
            total_messages = chat_history_repo.get_total_messages()
            messages_today = chat_history_repo.get_messages_count_by_period("today")
            messages_this_week = chat_history_repo.get_messages_count_by_period("this_week")
            messages_this_month = chat_history_repo.get_messages_count_by_period("this_month")
            
            # Get latest active chatbots with user info
            latest_chatbots = chatbot_repo.get_latest_active_chatbots(limit=10)
            for cb in latest_chatbots:
                if cb.get("account_id"):
                    user = users_repo.find_one({"account_id": cb["account_id"]})
                    if user:
                        cb["user_name"] = user.get("fullname", "")
                    if cb.get("workspace_id"):
                        cb["message_count"] = chat_history_repo.count_messages_by_chatbot(cb["workspace_id"])
                        cb["last_active_at"] = chat_history_repo.get_latest_message_by_chatbot(cb["workspace_id"])
            
            top_users = chat_history_repo.get_top_users_by_messages(limit=10)
            
            return jsonify({
                "statusCode": 200,
                "message": "Success",
                "data": {
                    "total_users": total_users,
                    "active_users": active_users,
                    "total_chatbots": total_chatbots,
                    "active_chatbots": active_chatbots,
                    "total_messages": total_messages,
                    "messages_today": messages_today,
                    "messages_this_week": messages_this_week,
                    "messages_this_month": messages_this_month,
                    "latest_active_chatbots": latest_chatbots,
                    "top_users_by_messages": top_users
                }
            }), 200
        except Exception as e:
            Log.error(f"[Admin API] Error getting dashboard: {e}")
            return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500
    
    @app.route("/api/admin/stats/messages", methods=["GET"])
    @require_auth
    def get_message_stats():
        """Get message statistics by period"""
        try:
            if g.user.get("role") != 0:
                return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
            
            period = request.args.get("period", "week")
            
            stats = chat_history_repo.get_message_stats(period=period)
            
            return jsonify({
                "statusCode": 200,
                "message": "Success",
                "data": {
                    "period": period,
                    "data": stats
                }
            }), 200
        except Exception as e:
            Log.error(f"[Admin API] Error getting message stats: {e}")
            return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500
    
    @app.route("/api/admin/chatbots/<chatbot_id>/toggle-active", methods=["PUT"])
    @require_auth
    def toggle_chatbot_active(chatbot_id):
        """Toggle chatbot active status (soft delete)"""
        try:
            if g.user.get("role") != 0:
                return jsonify({"statusCode": 403, "message": "Access denied. Admin only."}), 403
            
            result = chatbot_repo.toggle_chatbot_active(chatbot_id)
            if not result:
                return jsonify({"statusCode": 404, "message": "Chatbot not found"}), 404
            
            return jsonify({
                "statusCode": 200,
                "message": "Chatbot status updated successfully",
                "data": result
            }), 200
        except Exception as e:
            Log.error(f"[Admin API] Error toggling chatbot active: {e}")
            return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500

