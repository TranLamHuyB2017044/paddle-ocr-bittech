from app.database.base_repository import BaseRepository
from app.models.user import User

class UsersRepository(BaseRepository):
    def __init__(self):
        super().__init__("users")
        # Create unique indexes
        self.collection.create_index("username", unique=True, sparse=True)

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


# Global instance
users_repo = UsersRepository()
