from datetime import datetime
from src.repositories.accounts_repository import accounts_repo
from src.repositories.users_repository import users_repo
from src.config import PLANS_CONFIG
from src.utils.logger import Log

class SubscriptionService:
    @staticmethod
    def check_quota(user, cost=1):
        """
        Core logic for quota verification:
        - Admin: Always True
        - Business Plan: Always True
        - Others: used_requests + cost <= max_requests
        """
        if user.get('role') == 0:
            return True, "Admin access granted"

        account_id = user.get('account_id')
        if not account_id:
             return False, "User has no associated account"

        # Quota reset is now manual only (by admin or on upgrade)
        account = accounts_repo.find_by_id(account_id)
        if not account:
            return False, "Account not found"

        plan_key = account.get('plan', 0)
        plan_cfg = PLANS_CONFIG.get(plan_key)

        if not plan_cfg:
             return False, f"Invalid plan: {plan_key}"

        if plan_cfg.get('is_unlimited'):
            return True, "Unlimited plan"

        max_requests = plan_cfg.get('max_requests_per_month', 0)
        used_requests = account.get('used_requests', 0)

        if used_requests + cost > max_requests:
            return False, f"Quota exceeded for plan {plan_key} ({used_requests + cost}/{max_requests})"

        return True, "Within quota"

    @staticmethod
    def get_quota_info(account_id):
        """Returns current usage and max quota for an account."""
        account = accounts_repo.find_by_id(account_id)
        if not account:
            return None
        
        plan_key = account.get('plan', 0)
        plan_cfg = PLANS_CONFIG.get(plan_key)
        
        return {
            "plan": plan_key,
            "used_requests": account.get('used_requests', 0),
            "max_requests": plan_cfg.get('max_requests_per_month'),
            "remaining_requests": (plan_cfg.get('max_requests_per_month') - account.get('used_requests', 0)) if not plan_cfg.get('is_unlimited') else "Unlimited",
            "reset_at": account.get('reset_at'), # Still return for display but not for auto-reset logic
            "max_users": plan_cfg.get('max_users')
        }

    @staticmethod
    def can_create_user(manager_user):
        """Checks if a manager can create more users based on their plan."""
        if manager_user.get('role') == 0:
            return True, "Admin can create unlimited users"
        
        if manager_user.get('role') != 1:
            return False, "Only admins and managers can create users"
            
        account_id = manager_user.get('account_id')
        account = accounts_repo.find_by_id(account_id)
        if not account:
            return False, "Account not found"
            
        plan_key = account.get('plan', 0)
        plan_cfg = PLANS_CONFIG.get(plan_key)
        
        current_users_count = users_repo.collection.count_documents({"account_id": account_id})
        
        max_users = plan_cfg.get('max_users', 1)
        
        # -1 means unlimited
        if max_users != -1 and current_users_count >= max_users:
            return False, f"User limit reached for plan {plan_key} ({current_users_count}/{max_users})"
            
        return True, "Success"

subscription_service = SubscriptionService()
