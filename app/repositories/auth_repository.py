from app.database.base_repository import BaseRepository
from app.models.auth_session import AuthSession
from typing import Optional

class AuthRepository(BaseRepository):
    def __init__(self):
        super().__init__("auth_sessions")
        # Index on refresh_token_hash for fast lookup
        self.collection.create_index("refresh_token_hash", unique=True)
        # Index on user_id to find all sessions of a user
        self.collection.create_index("user_id")

    def create_session(self, session: AuthSession) -> str:
        data = session.model_dump(by_alias=True, exclude_none=True)
        return self.create(data)

    def find_by_hash(self, token_hash: str):
        return self.find_one({"refresh_token_hash": token_hash})

    def revoke_session(self, token_hash: str) -> bool:
        """Revoke a session by hash"""
        try:
            result = self.collection.update_one(
                {"refresh_token_hash": token_hash},
                {"$set": {"revoked": True}}
            )
            return result.modified_count > 0
        except:
            return False

    def revoke_all_user_sessions(self, user_id: str):
        """Revoke ALL sessions for a user (e.g. change password)"""
        try:
            self.collection.update_many(
                {"user_id": user_id, "revoked": False},
                {"$set": {"revoked": True}}
            )
        except:
            pass

# Global Instance
auth_repo = AuthRepository()
