from src.core.database.base_repository import BaseRepository
from src.modules.auth.models.account import Account
from bson import ObjectId
from datetime import datetime, timedelta

class AccountRepository(BaseRepository):
    def __init__(self):
        super().__init__("accounts")

    def find_by_id(self, account_id):
        if isinstance(account_id, str):
            account_id = ObjectId(account_id)
        return self.collection.find_one({"_id": account_id})

    def create(self, account: dict):
        if 'created_at' not in account:
            account['created_at'] = datetime.now()
        if 'reset_at' not in account:
            account['reset_at'] = datetime.now() + timedelta(days=30)
        
        result = self.collection.insert_one(account)
        return result.inserted_id

    def update(self, account_id, update_data: dict):
        if isinstance(account_id, str):
            account_id = ObjectId(account_id)
        return self.collection.update_one({"_id": account_id}, {"$set": update_data})

    def increment_usage(self, account_id, amount=1):
        if isinstance(account_id, str):
            account_id = ObjectId(account_id)
        return self.collection.update_one({"_id": account_id}, {"$inc": {"used_requests": amount}})

    def reset_quota(self, account_id):
        if isinstance(account_id, str):
            account_id = ObjectId(account_id)
        next_reset = datetime.now() + timedelta(days=30)
        return self.collection.update_one(
            {"_id": account_id}, 
            {"$set": {"used_requests": 0, "reset_at": next_reset}}
        )

accounts_repo = AccountRepository()
