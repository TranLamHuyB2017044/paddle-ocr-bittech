"""API-key authentication and explicit role authorization."""
from functools import wraps
from hmac import compare_digest

from flask import request, jsonify, g

from src.shared.utils.security import hash_token


SUPPORTED_ROLES = frozenset({0, 1, 2, 4})  # 1/2 remain valid for existing manager/member accounts.


def _get_repos():
    from src.modules.auth.repositories.users_repository import users_repo
    from src.modules.auth.repositories.accounts_repository import accounts_repo
    return users_repo, accounts_repo


def authenticate_api_key(api_key):
    """Return an active, known-role user, or None. Never trust role from a request."""
    if not isinstance(api_key, str) or not api_key or len(api_key) > 512:
        return None
    clean_key = api_key[3:] if api_key.startswith("ak_") else api_key
    if clean_key.count(".") != 1:
        return None
    access_key, secret = clean_key.split(".", 1)
    if not access_key or not secret:
        return None
    users_repo, _ = _get_repos()
    user = users_repo.find_by_api_key_access(access_key)
    if not user:
        user = users_repo.find_by_api_key_access("ak_" + access_key)
    if not user or not user.get("_id") or user.get("active", True) is not True:
        return None
    role = user.get("role")
    if type(role) is not int or role not in SUPPORTED_ROLES:
        return None
    stored_hash = (user.get("api_key") or {}).get("hashed_secret")
    if not isinstance(stored_hash, str) or not compare_digest(hash_token(secret), stored_hash):
        return None
    return user


def require_auth(view):
    @wraps(view)
    def decorated(*args, **kwargs):
        user = authenticate_api_key(request.headers.get("x-api-key"))
        if user is None:
            return jsonify({"statusCode": 401, "message": "Valid API key for an active account is required"}), 401
        g.user_id = str(user["_id"])
        g.user = user

        users_repo, accounts_repo = _get_repos()
        # Preserve device exemptions used by existing machine-to-machine APIs.
        skip_device = user["role"] in (0, 4) or request.path.startswith(("/api/chatbot", "/api/rag", "/api/v1/crawl"))
        if not skip_device and user.get("account_id"):
            account = accounts_repo.find_by_id(user["account_id"])
            skip_device = bool(account and account.get("plan") == 4)
        if not skip_device:
            device_id = request.headers.get("x-device-id")
            if not device_id or (user.get("deviceId") and user["deviceId"] != device_id):
                return jsonify({"statusCode": 401, "message": "Valid device ID is required"}), 401
            if not user.get("deviceId"):
                if not users_repo.update(g.user_id, {"deviceId": device_id}):
                    return jsonify({"statusCode": 401, "message": "Device could not be verified"}), 401
        return view(*args, **kwargs)
    return decorated


def optional_auth(view):
    """Anonymous access is allowed; a supplied invalid key must fail closed."""
    protected = require_auth(view)

    @wraps(view)
    def decorated(*args, **kwargs):
        if "x-api-key" in request.headers:
            return protected(*args, **kwargs)
        return view(*args, **kwargs)
    return decorated


def require_role(roles):
    if isinstance(roles, (int, str)):
        roles = [roles]
    allowed = frozenset(int(role) for role in roles)
    if not allowed or not allowed <= SUPPORTED_ROLES:
        raise ValueError("Unknown allowed role")

    def decorator(view):
        @wraps(view)
        def decorated(*args, **kwargs):
            user = getattr(g, "user", None)
            if not user:
                return jsonify({"statusCode": 401, "message": "Authentication required"}), 401
            role = user.get("role")
            if type(role) is not int or (role != 0 and role not in allowed):
                return jsonify({"statusCode": 403, "message": "Insufficient permissions"}), 403
            return view(*args, **kwargs)
        return decorated
    return decorator
