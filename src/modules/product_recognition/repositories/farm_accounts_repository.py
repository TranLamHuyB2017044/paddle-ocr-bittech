"""Server-managed ownership of farm product collections."""
from datetime import datetime, timezone

from src.core.database.base_repository import BaseRepository


class FarmAccountsRepository(BaseRepository):
    def __init__(self):
        super().__init__("farm_accounts")
        self.collection.create_index("farm_id", unique=True)
        self.collection.create_index("account_id")

    def find_by_farm(self, farm_id):
        return self.find_one({"farm_id": str(farm_id)})

    def assign(self, farm_id, account_id, actor_user_id):
        self.collection.update_one(
            {"farm_id": str(farm_id)},
            {"$set": {
                "account_id": str(account_id),
                "updated_by": str(actor_user_id),
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )

    def revoke(self, farm_id):
        return self.collection.delete_one({"farm_id": str(farm_id)}).deleted_count


farm_accounts_repo = FarmAccountsRepository()
