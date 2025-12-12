
from flask import Blueprint, request, jsonify
from cccd.services.oauth_service import oauth_service
from cccd.utils.logger import Log

auth_bp = Blueprint('auth_bp', __name__)

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


        # 4. Return Data
        # Note: You might want to strip sensitive token info or use a session cookie in a real app,
        # but for this specific request, we return the data to the FE to handle.
        return jsonify({
            "statusCode": 200,
            "message": "Login successful",
            "data": {
                "user": user_info,
                "credentials": {
                    "token": credentials.token,
                    "refresh_token": getattr(credentials, 'refresh_token', None),
                    "token_uri": getattr(credentials, 'token_uri', None),
                    "client_id": getattr(credentials, 'client_id', None),
                    "scopes": list(credentials.scopes) if credentials.scopes else []
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
