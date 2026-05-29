from datetime import datetime
from bson import ObjectId
from src.database.base_repository import BaseRepository

class ChatHistoryRepository(BaseRepository):
    def __init__(self):
        super().__init__("chat_histories")

    def save_message(self, workspace_id, user_id, question, answer, sources=None, provider=None):
        message = {
            "workspace_id": ObjectId(workspace_id) if isinstance(workspace_id, str) and ObjectId.is_valid(workspace_id) else workspace_id,
            "user_id": ObjectId(user_id) if isinstance(user_id, str) and ObjectId.is_valid(user_id) else user_id,
            "question": question,
            "answer": answer,
            "sources": sources or [],
            "provider": provider,
            "timestamp": datetime.utcnow()
        }
        return self.create(message)

    def get_history(self, workspace_id, limit=50):
        # Convert to ObjectId for querying
        wid = ObjectId(workspace_id) if isinstance(workspace_id, str) else workspace_id
        
        # Sort by timestamp ascending to show consistent conversation flow
        history = list(self.collection.find({"workspace_id": wid}).sort("timestamp", 1).limit(limit))
        
        # Format results for JSON response
        for h in history:
            h["_id"] = str(h["_id"])
            h["workspace_id"] = str(h["workspace_id"])
            h["user_id"] = str(h["user_id"])
            if "timestamp" in h:
                h["timestamp"] = h["timestamp"].isoformat()
                
        return history

    def clear_history(self, workspace_id):
        wid = ObjectId(workspace_id) if isinstance(workspace_id, str) else workspace_id
        result = self.collection.delete_many({"workspace_id": wid})
        return result.deleted_count

    def delete_by_user(self, user_id):
        uid = ObjectId(user_id) if isinstance(user_id, str) else user_id
        result = self.collection.delete_many({"user_id": uid})
        return result.deleted_count

chat_history_repo = ChatHistoryRepository()
