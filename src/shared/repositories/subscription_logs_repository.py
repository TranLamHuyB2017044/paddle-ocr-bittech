from src.database.base_repository import BaseRepository
from datetime import datetime

class SubscriptionLogsRepository(BaseRepository):
    def __init__(self):
        super().__init__("subscription_logs")

    def log_action(self, actor_id, target_account_id, action, from_plan, to_plan, details=None):
        """
        Log a subscription action.
        """
        log_entry = {
            "actor_id": actor_id, # The person who performed the action (Admin or User)
            "target_account_id": target_account_id,
            "action": action, # 'upgrade', 'renew', 'cancel', 'reset'
            "from_plan": from_plan,
            "to_plan": to_plan,
            "details": details,
            "created_at": datetime.utcnow()
        }
        return self.create(log_entry)

sub_logs_repo = SubscriptionLogsRepository()
