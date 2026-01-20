from functools import wraps
from flask import request, jsonify, g
from src.utils.security import decode_access_token
from src.repositories.users_repository import users_repo
from src.utils.security import hash_token

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # === API KEY AUTH ===
        api_key = None
        
        # 1. Check Authorization Header (Bearer ak_... or JWT)
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            
            # Try as API Key first (usually starts with ak_)
            if token.startswith("ak_"):
                api_key = token
            else:
                # Try as JWT
                try:
                    payload = decode_access_token(token)
                    if payload:
                        user_id = payload.get("sub")
                        user = users_repo.find_by_id(user_id)
                        if user:
                            g.user_id = str(user["_id"])
                            g.user = user
                            return f(*args, **kwargs)
                except Exception:
                    pass
            
        # 2. Fallback to Custom Header or Query Param for API Key
        if not api_key:
            api_key = request.headers.get("x-api-key") or request.args.get("api_key")
        
        if api_key:
            # 1. Parse Key Structure (ak_ACCESS.SECRET)
            if "." in api_key:
                try:
                    # Remove ak_ prefix if present
                    clean_key = api_key[3:] if api_key.startswith("ak_") else api_key
                    access_key, plain_secret = clean_key.split(".", 1)
                    
                    # 2. Find User by Access Key
                    user = users_repo.find_by_api_key_access(access_key)
                    
                    if user and user.get("api_key"):
                        # 3. Verify Secret
                        stored_hash = user["api_key"]["hashed_secret"]
                        input_hash = hash_token(plain_secret)
                        
                        if input_hash == stored_hash:
                            g.user_id = str(user["_id"])
                            g.user = user
                            
                            # Device ID Logic: First time login assignment
                            device_id = request.headers.get('X-Device-ID')
                            if not user.get('deviceId') and device_id:
                                users_repo.update(g.user_id, {"deviceId": device_id})
                                user['deviceId'] = device_id
                                
                            return f(*args, **kwargs)
                except ValueError:
                    pass 
            
            return jsonify({"statusCode": 401, "message": "Invalid API Key or Secret"}), 401

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
                return jsonify({"statusCode": 401, "message": "Authentication required"}), 401
            
            user_role = g.user.get('role', 2)
            if user_role == 0: # Admin can do everything
                return f(*args, **kwargs)
                
            if user_role not in roles:
                return jsonify({
                    "statusCode": 403, 
                    "message": f"Role '{user_role}' does not have permission to access this resource. Required: {roles}"
                }), 403
                
            return f(*args, **kwargs)
        return decorated_function
    return decorator
