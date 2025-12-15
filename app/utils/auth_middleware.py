from functools import wraps
from flask import request, jsonify, g
from app.utils.security import decode_access_token

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header:
             return jsonify({"statusCode": 401, "message": "Missing Authorization Header"}), 401
        
        try:
            token = auth_header.split(" ")[1]
            payload = decode_access_token(token)
            
            if not payload:
                return jsonify({"statusCode": 401, "message": "Invalid or Expired Token"}), 401
                
            # Lưu user_id vào global context của Flask để dùng trong controller
            g.user_id = payload.get("sub")
            
        except IndexError:
            return jsonify({"statusCode": 401, "message": "Token format error"}), 401
            
        return f(*args, **kwargs)
        
    return decorated
