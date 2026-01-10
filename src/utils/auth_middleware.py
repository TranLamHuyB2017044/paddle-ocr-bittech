from functools import wraps
from flask import request, jsonify, g
from src.utils.security import decode_access_token

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        # === API KEY AUTH ===
        api_key = None
        
        # 1. Check Authorization Header (Bearer ak_...)
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            api_key = auth_header.split(" ")[1]
            
        # 2. Fallback to Custom Header or Query Param
        if not api_key:
            api_key = request.headers.get("x-api-key") or request.args.get("api_key")
        
        if api_key:
            from src.repositories.users_repository import users_repo
            from src.utils.security import hash_token
            
            # 1. Parse Key Structure (ak_ACCESS.SECRET)
            if "." in api_key:
                try:
                    access_key, plain_secret = api_key.split(".", 1)
                    
                    # 2. Find User by Access Key
                    user = users_repo.find_by_api_key_access(access_key)
                    
                    if user and user.get("api_key"):
                        # 3. Verify Secret
                        stored_hash = user["api_key"]["hashed_secret"]
                        input_hash = hash_token(plain_secret)
                        
                        if input_hash == stored_hash:
                            g.user_id = str(user["_id"])
                            return f(*args, **kwargs)
                except ValueError:
                    pass # Format error, fall through
            
            # If we are here, auth failed
            return jsonify({"statusCode": 401, "message": "Invalid API Key or Secret"}), 401

        # Fallback if no API Key provided (Strict Mode: Require API Key)
        return jsonify({"statusCode": 401, "message": "Missing 'x-api-key' header"}), 401

        # === JWT AUTH (DISABLED) ===
        # auth_header = request.headers.get("Authorization")
        # if not auth_header:
        #      return jsonify({"statusCode": 401, "message": "Missing Authorization Header"}), 401
        
        # try:
        #     token = auth_header.split(" ")[1]
        #     payload = decode_access_token(token)
        #     
        #     if not payload:
        #         return jsonify({"statusCode": 401, "message": "Invalid or Expired Token"}), 401
        #         
        #     # Lưu user_id vào global context của Flask để dùng trong controller
        #     g.user_id = payload.get("sub")
        #     
        # except IndexError:
        #     return jsonify({"statusCode": 401, "message": "Token format error"}), 401
            
        return f(*args, **kwargs)
        
    return decorated
