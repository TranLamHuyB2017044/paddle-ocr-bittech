
from flask import Blueprint, request, jsonify, g
from src.services.oauth_service import oauth_service
from src.services.token_service import token_service
from src.services.auth_service_mongo import auth_service
from src.utils.auth_middleware import require_auth
from src.utils.logger import Log

auth_bp = Blueprint('auth_bp', __name__)

# ==================== AUTHENTICATION ROUTES (JWT) ====================

@auth_bp.route('/api/auth/register', methods=['POST'])
def register():
    try:
        data = request.json
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        fullname = data.get('fullname')
        phone = data.get('phone')
        
        if not email or not password or not username:
            return jsonify({"statusCode": 400, "message": "Email, password and username are required"}), 400
            
        user_id = auth_service.register(username, email, password, fullname, phone)
        
        return jsonify({
            "statusCode": 201,
            "message": "User registered successfully",
            "data": {"user_id": user_id}
        }), 201
    except ValueError as e:
        return jsonify({"statusCode": 400, "message": str(e)}), 400
    except Exception as e:
        Log.error(f"[Auth] Register failed: {e}")
        return jsonify({"statusCode": 500, "message": "Internal Server Error"}), 500

@auth_bp.route('/api/auth/login', methods=['POST'])
def login():
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({"statusCode": 400, "message": "Username and password are required"}), 400
            
        # Get Client Info
        user_agent = request.headers.get('User-Agent', 'Unknown')
        device_id = request.headers.get('X-Device-ID') # Client must send this header
        ip = request.remote_addr
        
        result = auth_service.login(username, password, user_agent, ip, device_id)
        
        return jsonify({
            "statusCode": 200,
            "message": "Login successful",
            "data": result
        })
    except ValueError as e:
        return jsonify({"statusCode": 401, "message": str(e)}), 401
    except Exception as e:
        Log.error(f"[Auth] Login failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@auth_bp.route('/api/auth/refresh', methods=['POST'])
def refresh():
    try:
        data = request.json
        refresh_token = data.get('refresh_token')
        
        if not refresh_token:
            return jsonify({"statusCode": 400, "message": "Refresh token is required"}), 400
            
        result = auth_service.reduce_refresh_token(refresh_token)
        
        return jsonify({
            "statusCode": 200,
            "message": "Token refreshed",
            "data": result
        })
    except ValueError as e:
        return jsonify({"statusCode": 401, "message": str(e)}), 401
    except Exception as e:
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@auth_bp.route('/api/auth/logout', methods=['POST'])
def logout():
    try:
        data = request.json
        refresh_token = data.get('refresh_token')
        if refresh_token:
            auth_service.logout(refresh_token)
            
        return jsonify({
            "statusCode": 200,
            "message": "Logged out successfully"
        })
    except Exception as e:
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@auth_bp.route('/api/auth/me', methods=['GET'])
@require_auth
def get_me():
    """Example of a protected route"""
    try:
        from src.repositories.users_repository import users_repo
        user = users_repo.find_by_id(g.user_id)
        if not user:
             return jsonify({"statusCode": 404, "message": "User not found"}), 404
             
        # Remove Sensitive Data
        user.pop("password", None)
        user["_id"] = str(user["_id"])
        
        return jsonify({
            "statusCode": 200,
            "data": user
        })
    except Exception as e:
        return jsonify({"statusCode": 500, "message": str(e)}), 500

# ==================== GOOGLE AUTH ROUTES (KEEPING EXISTING) ====================

@auth_bp.route('/api/auth/google-login', methods=['POST'])
def google_login():
    """
    Receives { "code": "AUTH_CODE_FROM_FE" }
    Exchanges for token, gets user info, ensures sheet exists.
    Returns: { "user": ..., "sheet": ..., "tokens": ... }
    """
    try:
        data = request.json
        auth_code = data.get('code')
        # redirect_uri is optional. For Web it's 'postmessage', for Mobile it might be None or specific scheme.
        redirect_uri = data.get('redirect_uri')

        if not auth_code:
            return jsonify({"statusCode": 400, "message": "Missing auth code"}), 400

        Log.info(f"[Auth] 🔐 Attempting login with redirect_uri: {redirect_uri}")
        
        # 1. Exchange Code
        credentials = oauth_service.exchange_code_for_credentials(auth_code, redirect_uri)
        
        # 2. Get User Info
        user_info = oauth_service.get_user_info(credentials)
        email = user_info.get('email')
        fullname = user_info.get('name')

        # 3. Login/Register in App DB
        user_agent = request.headers.get('User-Agent', 'Unknown')
        device_id = request.headers.get('X-Device-ID') 
        ip = request.remote_addr
        
        auth_result = auth_service.login_with_google(
            email=email,
            fullname=fullname,
            user_agent=user_agent,
            ip=ip,
            device_id=device_id
        )

        # 4. Return Data
        return jsonify({
            "statusCode": 200,
            "message": "Login successful",
            "data": {
                "user": auth_result['user'],
                "access_token": auth_result['access_token'],
                "refresh_token": auth_result['refresh_token'],
                "google_info": user_info,
                "google_credentials": {
                    "token": credentials.token,
                    "refresh_token": getattr(credentials, 'refresh_token', None),
                    "token_uri": getattr(credentials, 'token_uri', None),
                    "client_id": getattr(credentials, 'client_id', None),
                    "scopes": list(credentials.scopes) if credentials.scopes else [],
                    "has_drive_permissions": getattr(credentials, 'has_drive_permissions', False)
                }
            }
        })

    except FileNotFoundError as e:
        return jsonify({"statusCode": 500, "message": str(e)}), 500
    except Exception as e:
        import traceback
        error_trace = traceback.format_exc()
        Log.error(f"[Auth] ❌ Login failed: {e}\nTraceback:\n{error_trace}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@auth_bp.route('/api/auth/google/drive-connect', methods=['POST'])
def google_drive_connect():
    """
    Receives { "code": "AUTH_CODE", "redirect_uri": "..." }
    Exchanges code for Access, Refresh Token.
    Saves User Tokens to 'Database' (user_tokens.json).
    Returns 200 OK.
    """
    try:
        data = request.json
        auth_code = data.get('code')
        redirect_uri = data.get('redirect_uri')
        
        if not auth_code:
            return jsonify({"statusCode": 400, "message": "Missing auth code"}), 400

        Log.info(f"[Auth] 🔗 Drive Connect: Exchanging code with redirect_uri: {redirect_uri}")
        
        # 1. Exchange Code with Drive Scopes
        from src.services.oauth_service import DRIVE_SCOPES
        credentials = oauth_service.exchange_code_for_credentials(auth_code, redirect_uri, scopes=DRIVE_SCOPES)
        
        # 2. Get User Info
        user_info = oauth_service.get_user_info(credentials)
        email = user_info.get('email')
        
        if not email:
            return jsonify({"statusCode": 400, "message": "Could not retrieve user email"}), 400

        # 3. Prepare Token Data
        # Ensure we capture everything needed to refresh
        token_data = {
            "token": credentials.token,
            "refresh_token": getattr(credentials, 'refresh_token', None),
            "token_uri": getattr(credentials, 'token_uri', None),
            "client_id": getattr(credentials, 'client_id', None),
            "client_secret": getattr(credentials, 'client_secret', None),
            "scopes": list(credentials.scopes) if credentials.scopes else [],
            "expiry": credentials.expiry.isoformat() if hasattr(credentials, 'expiry') and credentials.expiry else None
        }
        
        # 4. Save to DB
        token_service.save_user_tokens(email, token_data)
        
        Log.info(f"[Auth] ✅ Saved Drive tokens for {email}")

        return jsonify({
            "statusCode": 200, 
            "message": "Drive connection successful",
            "data": {
                "user": user_info,
                "has_drive_permissions": getattr(credentials, 'has_drive_permissions', False)
            }
        })
        
    except Exception as e:
        Log.error(f"[Auth] ❌ Drive Connect failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@auth_bp.route('/api/auth/google/drive-disconnect', methods=['POST'])
@require_auth
def google_drive_disconnect():
    """
    Disconnects user's Google Drive by:
    1. Deleting stored tokens from database
    2. Optionally revoking access on Google's side
    
    Requires: JWT Authentication (user must be logged in)
    Optional Body: { "revoke": true } - to also revoke on Google
    
    Returns: 200 OK with disconnection status
    """
    try:
        from src.repositories.users_repository import users_repo
        import requests
        
        # Get authenticated user
        user_id = g.user_id
        user_data = users_repo.find_by_id(user_id)
        
        if not user_data:
            return jsonify({"statusCode": 404, "message": "User not found"}), 404
        
        email = user_data.get('email')
        if not email:
            return jsonify({"statusCode": 400, "message": "User email not found"}), 400
        
        # Check if user wants to revoke on Google's side
        data = request.json or {}
        should_revoke = data.get('revoke', False)
        
        revoke_status = None
        
        # If revoke requested, try to revoke on Google
        if should_revoke:
            tokens = token_service.get_user_tokens(email)
            if tokens and tokens.get('token'):
                try:
                    # Revoke token on Google's side
                    revoke_url = f"https://oauth2.googleapis.com/revoke?token={tokens['token']}"
                    response = requests.post(revoke_url)
                    
                    if response.status_code == 200:
                        revoke_status = "success"
                        Log.info(f"[Auth] ✅ Revoked Google token for {email}")
                    else:
                        revoke_status = "failed"
                        Log.warning(f"[Auth] ⚠️ Failed to revoke Google token: {response.status_code}")
                except Exception as e:
                    revoke_status = "error"
                    Log.error(f"[Auth] ❌ Error revoking token: {e}")
        
        # Delete tokens from our database
        deleted = token_service.delete_user_tokens(email)
        
        if deleted:
            return jsonify({
                "statusCode": 200,
                "message": "Drive disconnected successfully",
                "data": {
                    "email": email,
                    "tokens_deleted": True,
                    "revoke_status": revoke_status
                }
            }), 200
        else:
            return jsonify({
                "statusCode": 404,
                "message": "No Drive connection found for this user",
                "data": {
                    "email": email,
                    "tokens_deleted": False,
                    "revoke_status": revoke_status
                }
            }), 404
            
    except Exception as e:
        Log.error(f"[Auth] ❌ Drive Disconnect failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500
