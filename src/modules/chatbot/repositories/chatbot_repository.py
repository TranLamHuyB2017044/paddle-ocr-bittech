from datetime import datetime, timezone
from bson import ObjectId
from src.core.database.base_repository import BaseRepository
from typing import Optional
import secrets

class ChatbotRepository(BaseRepository):
    def __init__(self):
        super().__init__("chatbots")
        # Create unique index to ensure 1-1 relationship between workspace and chatbot
        self.collection.create_index("workspace_id", unique=True, sparse=True)
    
    def generate_public_token(self) -> str:
        """Generate a secure public token for chatbot embed"""
        return f"cb_{secrets.token_urlsafe(32)}"
    
    def create_chatbot(self, name: str, account_id: str, workspace_id: Optional[str] = None, description: Optional[str] = None, avatar_url: Optional[str] = None, color: int = 0, greeting: Optional[str] = None, telegram_bot_token: Optional[str] = None, telegram_chat_id: Optional[str] = None, workflow_webhook_url: Optional[str] = None, collect_contact_info: bool = True) -> str:
        """Create a new chatbot and return its string ID"""
        # If workspace_id is provided, check if it's already used by another chatbot
        if workspace_id:
            existing_chatbot = self.find_one({"workspace_id": ObjectId(workspace_id)})
            if existing_chatbot:
                raise ValueError("Workspace này đã được dùng bởi một chatbot khác")
        
        chatbot = {
            "name": name,
            "description": description,
            "avatar_url": avatar_url,
            "color": color,
            "greeting": greeting,
            "telegram_bot_token": telegram_bot_token,
            "telegram_chat_id": telegram_chat_id,
            "workflow_webhook_url": workflow_webhook_url,
            "collect_contact_info": collect_contact_info,
            "workspace_id": ObjectId(workspace_id) if workspace_id else None,
            "public_token": self.generate_public_token(),
            "account_id": ObjectId(account_id),
            "is_active": True,
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc)
        }
        return self.create(chatbot)
    
    def find_by_public_token(self, public_token: str):
        """Find active chatbot by public token"""
        return self.find_one({"public_token": public_token, "is_active": True})
    
    def find_by_account_id(self, account_id: str):
        """Find all chatbots for an account"""
        return list(self.find_all({"account_id": ObjectId(account_id), "is_active": True}))

    def get_chatbots_by_user(self, account_id, page=1, limit=20):
        """Get chatbots by account ID with pagination"""
        skip = (page - 1) * limit
        chatbots = list(self.collection.find({"account_id": ObjectId(account_id)}).sort("created_at", -1).skip(skip).limit(limit))
        
        for chatbot in chatbots:
            chatbot["id"] = str(chatbot["_id"])
            del chatbot["_id"]
            chatbot["account_id"] = str(chatbot["account_id"])
            if chatbot.get("workspace_id"):
                chatbot["workspace_id"] = str(chatbot["workspace_id"])
        
        return chatbots

    def count_chatbots_by_user(self, account_id):
        """Count chatbots by account ID"""
        return self.collection.count_documents({"account_id": ObjectId(account_id)})

    def get_chatbot_with_details(self, chatbot_id):
        """Get chatbot with detailed information"""
        chatbot = self.find_by_id(chatbot_id)
        if not chatbot:
            return None
        
        chatbot["id"] = str(chatbot["_id"])
        del chatbot["_id"]
        chatbot["account_id"] = str(chatbot["account_id"])
        if chatbot.get("workspace_id"):
            chatbot["workspace_id"] = str(chatbot["workspace_id"])
        
        return chatbot

    def get_latest_active_chatbots(self, limit=10):
        """Get latest active chatbots"""
        chatbots = list(self.collection.find({"is_active": True}).sort("updated_at", -1).limit(limit))
        
        for chatbot in chatbots:
            chatbot["id"] = str(chatbot["_id"])
            del chatbot["_id"]
            chatbot["account_id"] = str(chatbot["account_id"])
            if chatbot.get("workspace_id"):
                chatbot["workspace_id"] = str(chatbot["workspace_id"])
        
        return chatbots

    def get_total_chatbots(self, active_only=False):
        """Get total chatbots count"""
        query = {}
        if active_only:
            query["is_active"] = True
        return self.collection.count_documents(query)

    def get_all_chatbots(self, page=1, limit=20, search=None, active=None):
        """Get all chatbots with pagination and search"""
        query = {}
        
        if search:
            search_regex = {"$regex": search, "$options": "i"}
            query["$or"] = [
                {"name": search_regex},
                {"description": search_regex}
            ]
        
        if active is not None:
            query["is_active"] = active
        
        skip = (page - 1) * limit
        chatbots = list(self.collection.find(query).sort("created_at", -1).skip(skip).limit(limit))
        
        for chatbot in chatbots:
            chatbot["id"] = str(chatbot["_id"])
            del chatbot["_id"]
            chatbot["account_id"] = str(chatbot["account_id"])
            if chatbot.get("workspace_id"):
                chatbot["workspace_id"] = str(chatbot["workspace_id"])
        
        return chatbots

    def count_all_chatbots(self, search=None, active=None):
        """Count all chatbots"""
        query = {}
        
        if search:
            search_regex = {"$regex": search, "$options": "i"}
            query["$or"] = [
                {"name": search_regex},
                {"description": search_regex}
            ]
        
        if active is not None:
            query["is_active"] = active
        
        return self.collection.count_documents(query)

    def toggle_chatbot_active(self, chatbot_id):
        """Toggle chatbot active status"""
        from bson import ObjectId
        from datetime import datetime, timezone
        
        chatbot = self.find_by_id(chatbot_id)
        if not chatbot:
            return None
        
        new_active = not chatbot.get("is_active", True)
        
        # Update in DB
        self.collection.update_one(
            {"_id": ObjectId(chatbot_id)},
            {
                "$set": {
                    "is_active": new_active,
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )
        
        # Return updated chatbot
        updated = self.find_by_id(chatbot_id)
        if not updated:
            return None
            
        updated["id"] = str(updated["_id"])
        del updated["_id"]
        updated["account_id"] = str(updated["account_id"])
        if updated.get("workspace_id"):
            updated["workspace_id"] = str(updated["workspace_id"])
        
        return updated

chatbot_repo = ChatbotRepository()
