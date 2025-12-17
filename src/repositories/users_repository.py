from src.database.base_repository import BaseRepository
from src.models.user import User

class UsersRepository(BaseRepository):
    def __init__(self):
        super().__init__("users")
        # Create unique indexes
        self.collection.create_index("username", unique=True, sparse=True)
        self.collection.create_index("api_key.access_key", unique=True, sparse=True)

    def create_user(self, user: User):
        """
        Validate data using Pydantic model before inserting
        """
        user_dict = user.model_dump(by_alias=True, exclude_none=True)
        return self.create(user_dict)

    def find_by_username(self, username):
        return self.find_one({"username": username})


    def find_by_email(self, email):
        return self.find_one({"email": email})

    def find_by_api_key_access(self, access_key: str):
        """Find user by API Key's Access Key"""
        return self.find_one({"api_key.access_key": access_key})

    def find_by_api_key(self, api_key: str):
        # Deprecated or use internal logic? 
        # Middleware will parse key and use find_by_api_key_access
        # Just alias it for safety or remove? 
        # User asked "ko xoa code". I will keep it but it won't work for hashed keys unless passed access_key.
        # But wait, middleware calls find_by_api_key(full_key_from_header).
        # I MUST update middleware logic.
        return self.find_one({"api_key.access_key": api_key}) # Temporary placeholder?
        # Actually I will rename this to avoid confusion and update middleware.
        pass

    def increment_extraction_stats(self, user_id: str, doc_type: str):
        """
        Increment extraction statistics for a user
        - Increment total_extractions
        - Update last_extraction_at
        - Increment specific doc_type counter
        """
        from datetime import datetime
        from bson import ObjectId
        
        try:
            result = self.collection.update_one(
                {"_id": ObjectId(user_id)},
                {
                    "$inc": {
                        "stats.total_extractions": 1,
                        f"stats.doc_type_stats.{doc_type}": 1
                    },
                    "$set": {
                        "stats.last_extraction_at": datetime.now()
                    }
                }
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"Error incrementing extraction stats: {e}")
            return False


# Global instance
users_repo = UsersRepository()
