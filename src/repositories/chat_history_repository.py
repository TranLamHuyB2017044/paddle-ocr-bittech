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

chat_history_repo = ChatHistoryRepository()
