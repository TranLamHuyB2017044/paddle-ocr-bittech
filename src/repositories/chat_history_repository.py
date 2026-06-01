from datetime import datetime, timedelta
from bson import ObjectId
from src.database.base_repository import BaseRepository
import re
from collections import Counter

class ChatHistoryRepository(BaseRepository):
    def __init__(self):
        super().__init__("chat_histories")

    def save_message(self, workspace_id, user_id, question, answer, sources=None, provider=None, session_id=None, customer_info=None):
        message = {
            "workspace_id": ObjectId(workspace_id) if isinstance(workspace_id, str) and ObjectId.is_valid(workspace_id) else workspace_id,
            "user_id": ObjectId(user_id) if isinstance(user_id, str) and ObjectId.is_valid(user_id) else user_id,
            "session_id": session_id,
            "question": question,
            "answer": answer,
            "sources": sources or [],
            "provider": provider,
            "customer_info": customer_info or {},
            "timestamp": datetime.utcnow()
        }
        return self.create(message)

    def get_history(self, workspace_id, limit=50, session_id=None):
        # Convert to ObjectId for querying
        query = {"workspace_id": ObjectId(workspace_id) if isinstance(workspace_id, str) else workspace_id}
        
        if session_id:
            query["session_id"] = session_id
        
        # Sort by timestamp ascending to show consistent conversation flow
        history = list(self.collection.find(query).sort("timestamp", 1).limit(limit))
        
        # Format results for JSON response
        for h in history:
            h["_id"] = str(h["_id"])
            h["workspace_id"] = str(h["workspace_id"])
            h["user_id"] = str(h["user_id"]) if h.get("user_id") else None
            if "timestamp" in h:
                h["timestamp"] = h["timestamp"].isoformat()
                
        return history

    def get_session_history(self, session_id, limit=100):
        history = list(self.collection.find({"session_id": session_id}).sort("timestamp", 1).limit(limit))
        for h in history:
            h["_id"] = str(h["_id"])
            h["workspace_id"] = str(h["workspace_id"])
            h["user_id"] = str(h["user_id"]) if h.get("user_id") else None
            if "timestamp" in h:
                h["timestamp"] = h["timestamp"].isoformat()
        return history

    def get_message_count_by_period(self, workspace_id, period="day"):
        wid = ObjectId(workspace_id) if isinstance(workspace_id, str) else workspace_id
        
        now = datetime.utcnow()
        if period == "day":
            start_date = now - timedelta(days=1)
        elif period == "week":
            start_date = now - timedelta(weeks=1)
        elif period == "month":
            start_date = now - timedelta(days=30)
        else:
            start_date = now - timedelta(days=1)
        
        return self.collection.count_documents({
            "workspace_id": wid,
            "timestamp": {"$gte": start_date}
        })

    def get_latest_message(self, workspace_id, session_id=None):
        query = {"workspace_id": ObjectId(workspace_id) if isinstance(workspace_id, str) else workspace_id}
        if session_id:
            query["session_id"] = session_id
        
        latest = self.collection.find_one(query, sort=[("timestamp", -1)])
        if latest:
            latest["_id"] = str(latest["_id"])
            latest["workspace_id"] = str(latest["workspace_id"])
            latest["user_id"] = str(latest["user_id"]) if latest.get("user_id") else None
            if "timestamp" in latest:
                latest["timestamp"] = latest["timestamp"].isoformat()
        return latest

    def get_top_keywords(self, workspace_id, period="day", top_n=10):
        wid = ObjectId(workspace_id) if isinstance(workspace_id, str) else workspace_id
        
        now = datetime.utcnow()
        if period == "day":
            start_date = now - timedelta(days=1)
        elif period == "week":
            start_date = now - timedelta(weeks=1)
        elif period == "month":
            start_date = now - timedelta(days=30)
        else:
            start_date = now - timedelta(days=1)
        
        # Get all questions from the period
        messages = list(self.collection.find({
            "workspace_id": wid,
            "timestamp": {"$gte": start_date}
        }, {"question": 1}))
        
        # Extract and count keywords
        all_text = " ".join([msg["question"] for msg in messages])
        # Simple word extraction (remove punctuation, split into words)
        words = re.findall(r'\b\w+\b', all_text.lower())
        # Filter out common Vietnamese stop words (you can expand this list)
        stop_words = {"và", "là", "có", "của", "cho", "được", "từ", "trong", "với", "như", "này", "đó", "những", "để", "một", "nhiều", "khi", "nếu", "vì", "thì", "lại", "cũng", "đã", "sẽ", "rồi", "vẫn", "chỉ", "quá", "càng", "mà", "hay", "hoặc", "đến", "tới", "từ", "qua", "theo", "về", "của"}
        filtered_words = [word for word in words if word not in stop_words and len(word) > 1]
        
        # Count frequency
        word_counts = Counter(filtered_words)
        return word_counts.most_common(top_n)

    def get_all_sessions(self, workspace_id, limit=50):
        wid = ObjectId(workspace_id) if isinstance(workspace_id, str) else workspace_id
        
        # Get all unique session_ids with their latest message
        pipeline = [
            {"$match": {"workspace_id": wid}},
            {"$sort": {"timestamp": -1}},
            {"$group": {
                "_id": "$session_id",
                "latest_timestamp": {"$first": "$timestamp"},
                "latest_question": {"$first": "$question"},
                "customer_info": {"$first": "$customer_info"},
                "message_count": {"$sum": 1}
            }},
            {"$sort": {"latest_timestamp": -1}},
            {"$limit": limit}
        ]
        
        sessions = list(self.collection.aggregate(pipeline))
        for s in sessions:
            s["session_id"] = s["_id"]
            del s["_id"]
            s["latest_timestamp"] = s["latest_timestamp"].isoformat() if s.get("latest_timestamp") else None
        return sessions

    def clear_history(self, workspace_id):
        wid = ObjectId(workspace_id) if isinstance(workspace_id, str) else workspace_id
        result = self.collection.delete_many({"workspace_id": wid})
        return result.deleted_count

    def delete_by_user(self, user_id):
        uid = ObjectId(user_id) if isinstance(user_id, str) else user_id
        result = self.collection.delete_many({"user_id": uid})
        return result.deleted_count

    def get_messages_by_chatbot(self, workspace_id, page=1, limit=20, session_id=None):
        """Get messages by workspace ID with pagination"""
        wid = ObjectId(workspace_id) if isinstance(workspace_id, str) else workspace_id
        query = {"workspace_id": wid}
        
        if session_id:
            query["session_id"] = session_id
        
        skip = (page - 1) * limit
        messages = list(self.collection.find(query).sort("timestamp", -1).skip(skip).limit(limit))
        
        for msg in messages:
            msg["id"] = str(msg["_id"])
            del msg["_id"]
            msg["workspace_id"] = str(msg["workspace_id"])
            if msg.get("user_id"):
                msg["user_id"] = str(msg["user_id"])
            if msg.get("timestamp"):
                msg["timestamp"] = msg["timestamp"].isoformat()
        
        return messages

    def count_messages_by_chatbot(self, workspace_id):
        """Count messages by workspace ID"""
        wid = ObjectId(workspace_id) if isinstance(workspace_id, str) else workspace_id
        return self.collection.count_documents({"workspace_id": wid})

    def get_total_messages(self):
        """Get total messages in system"""
        return self.collection.count_documents({})

    def get_message_stats(self, period="week"):
        """Get message stats by period"""
        from datetime import datetime, timedelta
        
        now = datetime.utcnow()
        stats = []
        
        if period == "day":
            # Last 24 hours, per hour
            for i in range(24):
                start = now - timedelta(hours=(23 - i))
                end = start + timedelta(hours=1)
                count = self.collection.count_documents({
                    "timestamp": {"$gte": start, "$lt": end}
                })
                stats.append({
                    "date": start.strftime("%Y-%m-%d %H:00"),
                    "count": count
                })
        elif period == "week":
            # Last 7 days
            for i in range(7):
                date = now - timedelta(days=(6 - i))
                start = datetime(date.year, date.month, date.day)
                end = start + timedelta(days=1)
                count = self.collection.count_documents({
                    "timestamp": {"$gte": start, "$lt": end}
                })
                stats.append({
                    "date": start.strftime("%Y-%m-%d"),
                    "count": count
                })
        elif period == "month":
            # Last 30 days
            for i in range(30):
                date = now - timedelta(days=(29 - i))
                start = datetime(date.year, date.month, date.day)
                end = start + timedelta(days=1)
                count = self.collection.count_documents({
                    "timestamp": {"$gte": start, "$lt": end}
                })
                stats.append({
                    "date": start.strftime("%Y-%m-%d"),
                    "count": count
                })
        elif period == "year":
            # Last 12 months
            for i in range(12):
                months_ago = 11 - i
                year = now.year
                month = now.month - months_ago
                if month <= 0:
                    month += 12
                    year -= 1
                start = datetime(year, month, 1)
                if month == 12:
                    end = datetime(year + 1, 1, 1)
                else:
                    end = datetime(year, month + 1, 1)
                count = self.collection.count_documents({
                    "timestamp": {"$gte": start, "$lt": end}
                })
                stats.append({
                    "date": start.strftime("%Y-%m"),
                    "count": count
                })
        
        return stats

    def get_latest_message_by_chatbot(self, workspace_id):
        """Get latest message for a chatbot"""
        wid = ObjectId(workspace_id) if isinstance(workspace_id, str) else workspace_id
        msg = self.collection.find_one({"workspace_id": wid}, sort=[("timestamp", -1)])
        if msg:
            if msg.get("timestamp"):
                return msg["timestamp"].isoformat()
        return None

    def get_latest_message_by_user_account(self, account_id):
        """Get latest message for a user's account"""
        # First get all chatbots for this account
        from src.repositories.chatbot_repository import chatbot_repo
        chatbots = chatbot_repo.find_by_account_id(account_id)
        if not chatbots:
            return None
        
        workspace_ids = [cb["workspace_id"] for cb in chatbots if cb.get("workspace_id")]
        if not workspace_ids:
            return None
        
        msg = self.collection.find_one({"workspace_id": {"$in": workspace_ids}}, sort=[("timestamp", -1)])
        if msg:
            if msg.get("timestamp"):
                return msg["timestamp"].isoformat()
        return None

    def get_top_users_by_messages(self, limit=10):
        """Get top users by message count"""
        from bson import ObjectId
        
        # First, we need to map chatbots to users (chatbot -> account -> user)
        # Let's aggregate message count by workspace_id first
        pipeline = [
            {"$group": {
                "_id": "$workspace_id",
                "count": {"$sum": 1}
            }},
            {"$sort": {"count": -1}},
            {"$limit": limit * 2}  # Get extra to account for any issues
        ]
        
        workspace_stats = list(self.collection.aggregate(pipeline))
        
        # Now get chatbots and map to users
        result = []
        workspace_ids = [stat["_id"] for stat in workspace_stats if stat["_id"]]
        
        if workspace_ids:
            from src.repositories.chatbot_repository import chatbot_repo
            from src.repositories.users_repository import users_repo
            
            chatbots = list(chatbot_repo.collection.find({"workspace_id": {"$in": workspace_ids}}))
            account_ids = [cb["account_id"] for cb in chatbots]
            users = list(users_repo.collection.find({"account_id": {"$in": account_ids}}))
            
            # Create lookups
            chatbot_by_workspace = {str(cb["workspace_id"]): cb for cb in chatbots if cb.get("workspace_id")}
            user_by_account = {str(u["account_id"]): u for u in users if u.get("account_id")}
            
            for stat in workspace_stats:
                workspace_id = str(stat["_id"]) if isinstance(stat["_id"], ObjectId) else stat["_id"]
                chatbot = chatbot_by_workspace.get(workspace_id)
                if chatbot:
                    account_id_str = str(chatbot["account_id"])
                    user = user_by_account.get(account_id_str)
                    if user:
                        result.append({
                            "id": str(user["_id"]),
                            "fullname": user.get("fullname", ""),
                            "email": user.get("email", ""),
                            "message_count": stat["count"]
                        })
                        if len(result) >= limit:
                            break
        
        return result

    def get_messages_count_by_period(self, period="day"):
        """Get messages count for a specific period"""
        from datetime import datetime, timedelta
        
        now = datetime.utcnow()
        
        if period == "today":
            start = datetime(now.year, now.month, now.day)
        elif period == "this_week":
            start = now - timedelta(days=now.weekday())
            start = datetime(start.year, start.month, start.day)
        elif period == "this_month":
            start = datetime(now.year, now.month, 1)
        else:
            start = now - timedelta(days=1)
        
        return self.collection.count_documents({"timestamp": {"$gte": start}})


chat_history_repo = ChatHistoryRepository()
