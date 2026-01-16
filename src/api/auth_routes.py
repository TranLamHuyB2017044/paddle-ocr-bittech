
from flask import Blueprint, request, jsonify, g
from src.services.oauth_service import oauth_service
from src.services.token_service import token_service
from src.services.auth_service_mongo import auth_service
from src.services.multi_connect_service import call_client_register_post, call_system_connections_get, call_revoke_api_key
from src.repositories.users_repository import users_repo
from src.repositories.auth_service_repository import auth_service_repo
from src.models.user import User
from src.models.auth_service import AuthService
from src.utils.auth_middleware import require_auth
from src.utils.logger import Log

auth_bp = Blueprint('auth_bp', __name__)

# ==================== AUTHENTICATION ROUTES (JWT) ====================

@auth_bp.route('/api/user/update', methods=['PUT'])
@require_auth
def update_profile():
    try:
        data = request.json
        
        # Prevent updating sensitive fields
        allowed_fields = ["fullname", "phone", "avatar_url", "group_key", "user_id"]
        update_data = {k: v for k, v in data.items() if k in allowed_fields}
        
        if not update_data:
             return jsonify({"statusCode": 400, "message": "No valid fields to update"}), 400

        # Update
        success = users_repo.update(g.user_id, update_data)
        
        if success:
             # Fetch updated user to return
             updated_user = users_repo.find_by_id(g.user_id)
             if updated_user:
                 updated_user.pop("password", None)
                 updated_user["_id"] = str(updated_user["_id"])
                 
             return jsonify({
                 "statusCode": 200, 
                 "message": "User updated successfully",
                 "data": updated_user
             })
        else:
             return jsonify({"statusCode": 400, "message": "Update failed"}), 400

    except Exception as e:
        Log.error(f"[Auth] Update failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

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
            
        object_id, user_id_int = auth_service.register(username, email, password, fullname, phone)
        
        return jsonify({
            "statusCode": 201,
            "message": "User registered successfully",
            "data": {
                "id": str(object_id),
                "user_id": user_id_int
            }
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
        avatar_url = user_info.get('picture')

        # 3. Login/Register in App DB
        user_agent = request.headers.get('User-Agent', 'Unknown')
        device_id = request.headers.get('X-Device-ID') 
        ip = request.remote_addr
        
        auth_result = auth_service.login_with_google(
            email=email,
            fullname=fullname,
            user_agent=user_agent,
            ip=ip,
            avatar_url=avatar_url,
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
                "api_key": auth_result.get('api_key'),
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

@auth_bp.route('/api/auth/client-register', methods=['POST'])
@require_auth
def client_register():
    """
    Registers the current user with an external system.
    """
    try:
        data = request.json
        user_id = g.user_id
        
        # 1. Fetch User
        user_data = users_repo.find_by_id(user_id)
        if not user_data:
             return jsonify({"statusCode": 404, "message": "User not found"}), 404
             
        user = User(**user_data)
        
        # 2. Prepare Data
        external_id = user.user_id if user.user_id else str(user.id)
        
        # user_info as JSON string
        user_info_str = user.model_dump_json(by_alias=True)
        
        # 3. Call Service
        result = call_client_register_post(
            system_connection_id=data.get('system_connection_id'),
            system_id=data.get('system_id'),
            system_register=data.get('system_register'),
            external_id=external_id,
            description=data.get('description'),
            user_info=user_info_str
        )
        
        if result and result.get("success") is False:
             return jsonify({
                 "statusCode": 400, 
                 "message": result.get("message", "Registration failed"),
                 "data": result
             }), 400

        # --- NEW: Save record to local auth_services collection ---
        try:
            # Result is expected to be a dict. Successful structure: result["data"]["data"]
            if result and isinstance(result, dict) and result.get("data"):
                nested_data = result.get("data", {})
                # The actual fields are in result["data"]["data"] based on sample
                payload_data = nested_data.get("data") if isinstance(nested_data, dict) else None
                
                if payload_data and isinstance(payload_data, dict):
                    sys_conn = payload_data.get("system_connection", {})
                    
                    # Mapping according to user requirement:
                    # uuid is system_id
                    # userid is external_id
                    # app name is name
                    # key is api key
                    # app info is system_connection
                    
                    auth_svc = AuthService(
                        uuid=sys_conn.get("system_id"),
                        endpoint=sys_conn.get("endpoint"),
                        connection_type="hkb",
                        key=payload_data.get("api_key"),
                        user_id=payload_data.get("external_id"),
                        app_name=sys_conn.get("name"),
                        app_info=json.dumps(sys_conn, ensure_ascii=False)
                    )
                    
                    # Store in DB
                    auth_service_repo.create(auth_svc.model_dump(by_alias=True, exclude_none=True))
                    Log.info(f"[Auth] 💾 Saved AuthService record for user {auth_svc.user_id}, uuid: {auth_svc.uuid}")

        except Exception as save_err:
            Log.error(f"[Auth] ⚠️ Failed to save AuthService record locally: {save_err}")
            # We don't return error here because the external registration was successful

        return jsonify({
            "statusCode": 200,
            "message": "Client register called and saved successfully",
            "data": result
        })

    except Exception as e:
        Log.error(f"[Auth] ❌ Client Register failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

@auth_bp.route('/api/auth/system-connections/get', methods=['POST'])
@require_auth
def system_connections_get():
    """
    Calls system-connections/get.
    """
    try:
        data = request.json
        user_id = g.user_id

        # 1. Fetch User and their connections
        user_item = users_repo.find_by_id(user_id)
        if not user_item:
             return jsonify({"statusCode": 404, "message": "User not found"}), 404
             
        user_id_int = user_item.get("user_id")
        
        # Get all UUIDs from auth_services for this user
        connections = auth_service_repo.find_all({"user_id": user_id_int})
        client_register_uuids = [c.get("uuid") for c in connections if c.get("uuid")]
        
        if not client_register_uuids:
            client_register_uuids = [""]

        # 2. Call Service
        result = call_system_connections_get(
            group_key=data.get("group_key"),
            client_register=client_register_uuids
        )
        
        if result and isinstance(result, dict) and (result.get("success") is False):
             return jsonify({
                 "statusCode": 400, 
                 "message": result.get("message", "System Connections call failed"),
                 "data": result
             }), 400

        return jsonify({
            "statusCode": 200,
            "message": "System connections retrieved",
            "data": result
        })

    except Exception as e:
        Log.error(f"[Auth] ❌ System Connections Get failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500
        
@auth_bp.route('/api/auth/client-registers/revoke-api-key', methods=['POST'])
@require_auth
def revoke_api_key():
    """
    Revokes an API key from an external system and deletes the local AuthService record.
    Payload: { "system_id": "...", "password": "..." }
    """
    try:
        data = request.json
        system_id = data.get('system_id')
        password = data.get('password')
        user_id = g.user_id

        if not system_id or not password:
            return jsonify({"statusCode": 400, "message": "system_id and password are required"}), 400

        # 0. Find the record to get the API Key
        user_item = users_repo.find_by_id(user_id)
        if not user_item:
             return jsonify({"statusCode": 404, "message": "User not found"}), 404
        
        user_id_int = user_item.get("user_id")
        
        # Search for the connection record
        auth_record = auth_service_repo.collection.find_one({
            "user_id": user_id_int,
            "uuid": system_id
        })
        
        if not auth_record:
            return jsonify({
                "statusCode": 404, 
                "message": "No connection found for this system_id"
            }), 404
            
        api_key = auth_record.get("key")
        if not api_key:
             return jsonify({
                "statusCode": 400, 
                "message": "API Key not found in local record"
            }), 400

        # 1. Call External Service to Revoke
        result = call_revoke_api_key(system_id, api_key, password)

        # 2. Handle Result
        if result and result.get("status") == "success":
            # 3. Delete from local database
            auth_service_repo.collection.delete_one({"_id": auth_record["_id"]})
            
            Log.info(f"[Auth] 🗑️ Revoked and deleted AuthService record for user {user_id_int}, system_id: {system_id}")
            
            return jsonify({
                "statusCode": 200,
                "message": "API Key revoked successfully",
                "data": {
                    "system_id": system_id,
                    "external_response": result
                }
            })
        else:
            return jsonify({
                "statusCode": 400,
                "message": result.get("message", "Revocation failed"),
                "data": result
            }), 400

    except Exception as e:
        Log.error(f"[Auth] ❌ Revoke API Key failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500

