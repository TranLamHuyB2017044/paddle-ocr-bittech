from datetime import datetime, timezone
from bson import ObjectId
from src.database.base_repository import BaseRepository
import secrets

class ChatbotRepository(BaseRepository):
    def __init__(self):
        super().__init__("chatbots")
        # Create unique index to ensure 1-1 relationship between workspace and chatbot
        self.collection.create_index("workspace_id", unique=True, sparse=True)
    
    def generate_public_token(self) -> str:
        """Generate a secure public token for chatbot embed"""
        return f"cb_{secrets.token_urlsafe(32)}"
    
    def create_chatbot(self, name: str, account_id: str, workspace_id: str = None, description: str = None, avatar_url: str = None, color: int = 0, greeting: str = None, telegram_bot_token: str = None, telegram_chat_id: str = None) -> str:
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

chatbot_repo = ChatbotRepository()
