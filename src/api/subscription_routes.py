from flask import Blueprint, request, jsonify, g
from src.utils.auth_middleware import require_auth, require_role
from src.repositories.users_repository import users_repo
from src.repositories.accounts_repository import accounts_repo
from src.services.subscription_service import subscription_service
from src.utils.logger import Log

subscription_bp = Blueprint('subscription_bp', __name__)

@subscription_bp.route('/api/subscription/me', methods=['GET'])
@require_auth
def get_my_usage():
    """
    Get current user's subscription and usage info.
    Available to: ALL (Admin, Manager, User)
    """
    try:
        if not g.user:
            return jsonify({"statusCode": 401, "message": "User context missing"}), 401

        account_id = g.user.get('account_id')
        if not account_id:
             return jsonify({"statusCode": 404, "message": "No account associated with user"}), 404

        # Use the existing service logic to get formatted info
        quota_info = subscription_service.get_quota_info(account_id)
        
        if not quota_info:
             return jsonify({"statusCode": 404, "message": "Account not found"}), 404

        # Add user role info
        role_map = {0: "Admin", 1: "Manager", 2: "User"}
        user_role = g.user.get('role', 2)
        quota_info["user_role"] = user_role
        quota_info["user_role_name"] = role_map.get(user_role, "Unknown")

        return jsonify({
            "statusCode": 200,
            "data": quota_info
        }), 200
    except Exception as e:
        Log.error(f"[Sub] get_my_usage error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@subscription_bp.route('/api/subscription/manager/users-usage', methods=['GET'])
@require_auth
@require_role([0, 1]) # Admin(0) and Manager(1)
def get_manager_sub_users_usage():
    """
    Get usage statistics for all users under the current manager's account.
    """
    try:
        current_user = g.user
        
        # If Admin, they might provide ?account_id to inspect a specific manager's group
        # If Manager, they can only see their own.
        target_account_id = current_user.get('account_id')
        
        if current_user.get('role') == 0:
            requested_account_id = request.args.get('account_id')
            if requested_account_id:
                target_account_id = requested_account_id

        if not target_account_id:
             return jsonify({"statusCode": 400, "message": "Account ID mismatch"}), 400

        # Find all users with this account_id
        # We need to access collection directly or add method to repo. 
        # For now, accessing collection via repo is acceptable for read op.
        users = list(users_repo.collection.find(
            {"account_id": str(target_account_id)},
            {"password": 0, "api_key": 0} # Exclude secrets
        ))
        
        results = []
        role_map = {0: "Admin", 1: "Manager", 2: "User"}
        for u in users:
            stats = u.get('stats', {})
            role_id = u.get('role', 2)
            results.append({
                "user_id_str": str(u.get('_id')),
                "user_id_int": u.get('user_id'),
                "username": u.get('username'),
                "fullname": u.get('fullname'),
                "email": u.get('email'),
                "role": role_id,
                "role_name": role_map.get(role_id, "Unknown"),
                "total_usage": stats.get('total_extractions', 0),
                "last_active": stats.get('last_extraction_at')
            })

        return jsonify({
            "statusCode": 200,
            "data": {
                "account_id": target_account_id,
                "total_users": len(results),
                "users": results
            }
        }), 200

    except Exception as e:
        Log.error(f"[Sub] get_manager_sub_users_usage error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@subscription_bp.route('/api/subscription/cancel', methods=['POST'])
@require_auth
def cancel_subscription():
    """
    User cancels their current paid subscription and returns to Free plan (ID 0).
    Note: used_requests is NOT reset to prevent abuse.
    """
    try:
        if not g.user:
            return jsonify({"statusCode": 401, "message": "User context missing"}), 401

        account_id = g.user.get('account_id')
        if not account_id:
            return jsonify({"statusCode": 404, "message": "No account associated with user"}), 404

        # Update account to Free plan (0)
        success = accounts_repo.update(account_id, {"plan": 0})
        
        if success:
            Log.info(f"[Sub] User {g.user_id} cancelled subscription for account {account_id}")
            return jsonify({
                "statusCode": 200,
                "message": "Đã hủy gói dịch vụ thành công. Tài khoản của bạn đã được chuyển về gói Free.",
                "data": {
                    "account_id": str(account_id),
                    "new_plan": 0
                }
            }), 200
        else:
            return jsonify({"statusCode": 400, "message": "Không thể hủy gói vào lúc này."}), 400

    except Exception as e:
        Log.error(f"[Sub] cancel_subscription error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@subscription_bp.route('/api/subscription/admin/overview', methods=['GET'])
@require_auth
@require_role(0) # Admin ONLY
def get_admin_overview():
    """
    Get high-level overview of all accounts and their usage.
    """
    try:
        # 1. Get all accounts
        accounts = list(accounts_repo.collection.find())
        
        overview = []
        role_map = {0: "Admin", 1: "Manager", 2: "User"}
        for acc in accounts:
            acc_id = str(acc.get('_id'))
            
            # Find owner (usually the Manager or the first user with role 1/0 or just any user linked)
            owner = users_repo.collection.find_one({"account_id": acc_id})
            
            owner_info = None
            if owner:
                role_id = owner.get('role', 2)
                owner_info = {
                    "user_id": owner.get('user_id'),
                    "username": owner.get('username'),
                    "fullname": owner.get('fullname'),
                    "email": owner.get('email'),
                    "phone": owner.get('phone'),
                    "role": role_id,
                    "role_name": role_map.get(role_id, "Unknown"),
                    "stats": owner.get('stats', {}),
                    "created_at": owner.get('created_at')
                }

            # Also count total users in this account
            user_count = users_repo.collection.count_documents({"account_id": acc_id})

            overview.append({
                "account_id": acc_id,
                "owner": owner_info,
                "user_count": user_count,
                "plan": acc.get('plan', 0),
                "used_requests": acc.get('used_requests', 0),
                "reset_at": acc.get('reset_at'),
                "created_at": acc.get('created_at')
            })

        return jsonify({
            "statusCode": 200,
            "data": overview
        }), 200

    except Exception as e:
        Log.error(f"[Sub] get_admin_overview error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500
        
@subscription_bp.route('/api/subscription/plans', methods=['GET'])
def get_plans():
    """
    Get detailed subscription plans for UI display.
    """
    from src.config import PLANS_CONFIG
    
    plans_list = []
    for plan_id, config in PLANS_CONFIG.items():
        plans_list.append({
            "id": plan_id,
            **config
        })
        
    return jsonify({
        "statusCode": 200,
        "data": plans_list
    }), 200

@subscription_bp.route('/api/subscription/admin/upgrade-plan', methods=['POST'])
@require_auth
@require_role(0) # Admin ONLY
def admin_upgrade_plan():
    """
    Upgrade an account's plan by user_id or account_id.
    Resets usage to 0 and updates the plan.
    """
    try:
        data = request.json
        user_id_int = data.get('user_id')
        account_id = data.get('account_id')
        new_plan = data.get('plan')
        target_account_id = account_id
        
        # 1. Determine the Account ID
        if user_id_int and not target_account_id:
            user = users_repo.collection.find_one({"user_id": user_id_int})
            if not user:
                user = users_repo.find_by_id(str(user_id_int))
            
            if user:
                target_account_id = user.get('account_id')
            else:
                return jsonify({"statusCode": 404, "message": f"User {user_id_int} not found"}), 404

        if not target_account_id:
            return jsonify({"statusCode": 400, "message": "Could not determine account_id"}), 400

        # 2. Get current account info (to reuse plan if new_plan is not provided)
        account = accounts_repo.find_by_id(target_account_id)
        if not account:
            return jsonify({"statusCode": 404, "message": "Account not found"}), 404

        # Use existing plan if new_plan is not specified
        final_plan = new_plan if new_plan is not None else account.get('plan', 0)

        if final_plan == 0:
            return jsonify({"statusCode": 400, "message": "Gói Free không được phép gia hạn hoặc làm mới lượt dùng."}), 400

        from src.config import PLANS_CONFIG
        if final_plan not in PLANS_CONFIG:
            return jsonify({"statusCode": 400, "message": f"Invalid plan ID: {final_plan}"}), 400

        # 3. Update Account & Reset Quota
        update_data = {"plan": final_plan}
        success = accounts_repo.update(target_account_id, update_data)
        
        if success:
            # Also reset quota (this puts used_requests to 0 and adds +30 days)
            accounts_repo.reset_quota(target_account_id)
            
            action = "upgraded" if new_plan is not None else "renewed"
            Log.info(f"[Admin] Account {target_account_id} {action} to plan {final_plan}")
            
            return jsonify({
                "statusCode": 200,
                "message": f"Successfully {action} account to plan {PLANS_CONFIG[final_plan]['name']}",
                "data": {
                    "account_id": str(target_account_id),
                    "new_plan": final_plan,
                    "plan_name": PLANS_CONFIG[final_plan]['name'],
                    "action": action
                }
            }), 200
        else:
            return jsonify({"statusCode": 400, "message": "Failed to update account"}), 400

    except Exception as e:
        Log.error(f"[Sub] admin_upgrade_plan error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@subscription_bp.route('/api/subscription/admin/reset-account', methods=['POST'])
@require_auth
@require_role(0) # Admin ONLY
def admin_reset_account():
    """
    Force reset an account to Free plan (0) and reset usage to 0.
    Used for administrative actions/penalties.
    """
    try:
        data = request.json
        user_id_int = data.get('user_id')
        account_id = data.get('account_id')

        target_account_id = account_id
        
        # 1. Determine the Account ID
        if user_id_int and not target_account_id:
            user = users_repo.collection.find_one({"user_id": user_id_int})
            if not user:
                user = users_repo.find_by_id(str(user_id_int))
            
            if user:
                target_account_id = user.get('account_id')
            else:
                return jsonify({"statusCode": 404, "message": f"User {user_id_int} not found"}), 404

        if not target_account_id:
            return jsonify({"statusCode": 400, "message": "Could not determine account_id"}), 400

        # 2. Reset to Free Plan and 0 Usage
        # Update plan to 0
        accounts_repo.update(target_account_id, {"plan": 0})
        # Reset usage to 0 using existing repo method
        success = accounts_repo.reset_quota(target_account_id)
        
        if success:
            Log.info(f"[Admin] Account {target_account_id} has been FORCE RESET to Free plan with 0 usage.")
            return jsonify({
                "statusCode": 200,
                "message": "Tài khoản đã được đặt lại về gói Free với 0 lượt sử dụng.",
                "data": {
                    "account_id": str(target_account_id),
                    "plan": 0,
                    "used_requests": 0
                }
            }), 200
        else:
            return jsonify({"statusCode": 400, "message": "Không thể thực hiện reset tài khoản."}), 400

    except Exception as e:
        Log.error(f"[Sub] admin_reset_account error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500
