from functools import wraps
from flask import request, jsonify, g
from src.utils.security import decode_access_token
from src.repositories.users_repository import users_repo
from src.repositories.accounts_repository import accounts_repo
from src.utils.security import hash_token
from src.utils.logger import Log

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = None
        
        # 1. Check x-api-key Header ONLY
        api_key = request.headers.get("x-api-key")
        
        if api_key:
            # 1. Parse Key Structure (ak_ACCESS.SECRET)
            if "." in api_key:
                try:
                    # Handle raw key from header (which might or might not have ak_ prefix)
                    clean_key = api_key
                    if api_key.startswith("ak_"):
                         clean_key = api_key[3:]
                    access_key, plain_secret = clean_key.split(".", 1)
                    
                    # 2. Find User by Access Key
                    user = users_repo.find_by_api_key_access(access_key)
                    
                    # Legacy Support: If not found, try adding 'ak_' prefix (old key format in DB)
                    if not user:
                         user = users_repo.find_by_api_key_access("ak_" + access_key)
                    
                    if user and user.get("api_key"):
                        # 3. Verify Secret
                        stored_hash = user["api_key"]["hashed_secret"]
                        input_hash = hash_token(plain_secret)
                        
                        if input_hash == stored_hash:
                            g.user_id = str(user["_id"])
                            g.user = user
                            
                            # Check if we need to skip device check
                            skip_device_check = False
                            
                            # Skip for chatbot routes
                            if request.path.startswith('/api/chatbot'):
                                skip_device_check = True
                            
                            # Skip for plan 4 (Chatbot plan)
                            if user.get("account_id"):
                                account = accounts_repo.find_by_id(user.get("account_id"))
                                if account and account.get("plan") == 4:
                                    skip_device_check = True
                            
                            if not skip_device_check:
                                # Device ID Logic: First time login assignment or mismatch check
                                header_device_id = request.headers.get('x-device-id') or request.headers.get('X-Device-ID')
                                    
                                if not user.get('deviceId'):
                                    if header_device_id:
                                        users_repo.update(g.user_id, {"deviceId": header_device_id})
                                        user['deviceId'] = header_device_id
                                else:
                                    # If deviceId exists, we MUST verify match (Security)
                                    if header_device_id and user.get('deviceId') != header_device_id:
                                        Log.warning(f"[Auth] ⛔ Device mismatch for user {user.get('username')}: {header_device_id} != {user.get('deviceId')}")
                                        return jsonify({"statusCode": 401, "message": "Thiết bị không hợp lệ cho tài khoản này. Vui lòng đăng nhập lại."}), 401
                            
                            return f(*args, **kwargs)
                        else:
                            # Log invalid secret
                            print(f"Invalid secret for key {access_key}")
                    else:
                        print(f"User not found for access key {access_key}")
                except ValueError as e:
                    print(f"ValueError parsing key: {e}")
                    pass 
            
            Log.warning(f"[Auth] ❌ Access denied: Invalid API Key from {request.remote_addr}")
            return jsonify({"statusCode": 401, "message": "Invalid API Key"}), 401

        Log.warning(f"[Auth] ❌ Access denied: Authentication required for {request.path} from {request.remote_addr}")
        return jsonify({"statusCode": 401, "message": "Authentication required"}), 401
        
    return decorated

def require_role(roles):
    """Decorator to restrict access to specific roles."""
    if isinstance(roles, str):
        roles = [roles]
        
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not hasattr(g, 'user'):
                Log.warning(f"[Auth] ❌ Role check failed: User context missing for {request.path}")
                return jsonify({"statusCode": 401, "message": "Authentication required"}), 401
            
            user_role = g.user.get('role', 2)
            if user_role == 0: # Admin can do everything
                return f(*args, **kwargs)
                
            if user_role not in roles:
                Log.warning(f"[Auth] ❌ Permission denied: User {getattr(g, 'user_id', 'Unknown')} with role {user_role} tried to access {request.path}. Required: {roles}")
                return jsonify({
                    "statusCode": 403, 
                    "message": f"Role '{user_role}' does not have permission to access this resource. Required: {roles}"
                }), 403
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator
