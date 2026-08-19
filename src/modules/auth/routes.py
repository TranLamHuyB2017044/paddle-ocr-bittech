"""
Auth Module Routes
Handlers for Authentication, Google OAuth, External Connections, and License Management.
"""
import os
import json
import requests
import traceback
from datetime import datetime

from flask import Blueprint, request, jsonify, g
import cloudinary
import cloudinary.uploader

from src.shared.services.oauth_service import oauth_service
from src.shared.services.token_service import token_service
from src.shared.services.auth_service_mongo import auth_service
from src.shared.services.multi_connect_service import (
    call_client_register_post, call_system_connections_get,
    call_revoke_api_key, call_auth_token, upload_document
)
from src.shared.repositories.users_repository import users_repo
from src.shared.repositories.auth_service_repository import auth_service_repo
from src.shared.repositories.licenses_repository import licenses_repo
from src.shared.models.user import User
from src.shared.models.auth_service import AuthService
from src.shared.utils.auth_middleware import require_auth, require_role
from src.shared.utils.logger import Log


auth_bp = Blueprint('auth_bp', __name__)
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


# ── 1. GOOGLE AUTHENTICATION & DRIVE CONNECT ─────────────────────────────────

@auth_bp.route('/api/auth/google-login', methods=['POST'])
def google_login():
    try:
        data = request.json
        auth_code = data.get('code')
        redirect_uri = data.get('redirect_uri')

        if not auth_code:
            return jsonify({"statusCode": 400, "message": "Missing auth code"}), 400

        credentials = oauth_service.exchange_code_for_credentials(auth_code, redirect_uri)
        user_info = oauth_service.get_user_info(credentials)
        email = user_info.get('email')
        fullname = user_info.get('name')
        avatar_url = user_info.get('picture')

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
    except Exception as e:
        Log.error(f"[Auth] Google Login failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@auth_bp.route('/api/auth/google/drive-connect', methods=['POST'])
def google_drive_connect():
    try:
        data = request.json
        auth_code = data.get('code')
        redirect_uri = data.get('redirect_uri')
        
        if not auth_code:
            return jsonify({"statusCode": 400, "message": "Missing auth code"}), 400

        from src.shared.services.oauth_service import DRIVE_SCOPES
        credentials = oauth_service.exchange_code_for_credentials(auth_code, redirect_uri, scopes=DRIVE_SCOPES)
        user_info = oauth_service.get_user_info(credentials)
        email = user_info.get('email')
        
        if not email:
            return jsonify({"statusCode": 400, "message": "Could not retrieve user email"}), 400

        token_data = {
            "token": credentials.token,
            "refresh_token": getattr(credentials, 'refresh_token', None),
            "token_uri": getattr(credentials, 'token_uri', None),
            "client_id": getattr(credentials, 'client_id', None),
            "client_secret": getattr(credentials, 'client_secret', None),
            "scopes": list(credentials.scopes) if credentials.scopes else [],
            "expiry": credentials.expiry.isoformat() if hasattr(credentials, 'expiry') and credentials.expiry else None
        }
        
        token_service.save_user_tokens(email, token_data)
        return jsonify({
            "statusCode": 200, 
            "message": "Drive connection successful",
            "data": {
                "user": user_info,
                "has_drive_permissions": getattr(credentials, 'has_drive_permissions', False)
            }
        })
    except Exception as e:
        Log.error(f"[Auth] Drive Connect failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@auth_bp.route('/api/auth/google/drive-disconnect', methods=['POST'])
@require_auth
def google_drive_disconnect():
    try:
        user_id = g.user_id
        user_data = users_repo.find_by_id(user_id)
        if not user_data:
            return jsonify({"statusCode": 404, "message": "User not found"}), 404
        
        email = user_data.get('email')
        if not email:
            return jsonify({"statusCode": 400, "message": "User email not found"}), 400
        
        data = request.json or {}
        should_revoke = data.get('revoke', False)
        revoke_status = None
        
        if should_revoke:
            tokens = token_service.get_user_tokens(email)
            if tokens and tokens.get('token'):
                try:
                    revoke_url = f"https://oauth2.googleapis.com/revoke?token={tokens['token']}"
                    response = requests.post(revoke_url)
                    revoke_status = "success" if response.status_code == 200 else "failed"
                except Exception as e:
                    revoke_status = "error"
                    Log.error(f"[Auth] Error revoking token: {e}")
        
        deleted = token_service.delete_user_tokens(email)
        return jsonify({
            "statusCode": 200 if deleted else 404,
            "message": "Drive disconnected" if deleted else "No Drive connection found",
            "data": {"email": email, "tokens_deleted": deleted, "revoke_status": revoke_status}
        }), 200 if deleted else 404
    except Exception as e:
        Log.error(f"[Auth] Drive Disconnect failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── 2. EXTERNAL SYSTEM CONNECTIVITY (HKB / MULTI-CONNECT) ───────────────────

@auth_bp.route('/api/auth/client-register', methods=['POST'])
@require_auth
def client_register():
    try:
        data = request.json
        user_id = g.user_id
        user_data = users_repo.find_by_id(user_id)
        if not user_data:
            return jsonify({"statusCode": 404, "message": "User not found"}), 404
             
        user = User(**user_data)
        external_id = user.user_id if user.user_id else str(user.id)
        
        user_info_raw = data.get('user_info')
        if isinstance(user_info_raw, dict):
            user_info_str = json.dumps(user_info_raw, ensure_ascii=False)
        elif isinstance(user_info_raw, str):
            user_info_str = user_info_raw
        else:
            user_info_str = user.model_dump_json(by_alias=True)
        
        result = call_client_register_post(
            system_connection_id=data.get('system_connection_id'),
            system_id=data.get('system_id'),
            system_register=data.get('system_register'),
            external_id=external_id,
            description=data.get('description'),
            user_info=user_info_str
        )
        
        if result and result.get("success") is False:
            return jsonify({"statusCode": 400, "message": result.get("message", "Registration failed"), "data": result}), 400

        try:
            is_registered_success = result and isinstance(result, dict) and ((result.get("status") == "success") or (result.get("success") is True))
            if is_registered_success:
                first_level = result.get("data")
                if first_level and isinstance(first_level, dict):
                    payload_data = None
                    if isinstance(first_level.get("data"), dict) and "api_key" in first_level.get("data"):
                        payload_data = first_level.get("data")
                    elif "api_key" in first_level:
                        payload_data = first_level
                    elif isinstance(first_level.get("data"), dict):
                        payload_data = first_level.get("data")
                    
                    if payload_data and isinstance(payload_data, dict):
                        sys_conn = payload_data.get("system_connection", {})
                        auth_svc = AuthService(
                            uuid=sys_conn.get("system_id") if isinstance(sys_conn, dict) else payload_data.get("system_id"),
                            endpoint=sys_conn.get("endpoint") if isinstance(sys_conn, dict) else payload_data.get("endpoint"),
                            connection_type="hkb",
                            key=payload_data.get("api_key"),
                            user_id=payload_data.get("external_id"),
                            app_name=sys_conn.get("name") if isinstance(sys_conn, dict) else payload_data.get("app_name"),
                            app_info=json.dumps(sys_conn, ensure_ascii=False) if isinstance(sys_conn, dict) else "{}"
                        )
                        auth_service_repo.create(auth_svc.model_dump(by_alias=True, exclude_none=True))
        except Exception as save_err:
            Log.error(f"[Auth] Failed to save AuthService record locally: {save_err}")

        return jsonify({"statusCode": 200, "message": "Client register called successfully", "data": result})
    except Exception as e:
        Log.error(f"[Auth] Client Register failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@auth_bp.route('/api/auth/system-connections/get', methods=['POST'])
@require_auth
def system_connections_get():
    try:
        data = request.json
        user_id = g.user_id
        user_item = users_repo.find_by_id(user_id)
        if not user_item:
            return jsonify({"statusCode": 404, "message": "User not found"}), 404
             
        user_id_int = user_item.get("user_id")
        connections = auth_service_repo.find_all({"user_id": user_id_int})
        client_register_uuids = [c.get("uuid") for c in connections if c.get("uuid")] or [""]

        group_key_input = data.get("group_key")
        if isinstance(group_key_input, str):
            group_key_list = [k.strip() for k in group_key_input.split(",") if k.strip()]
        elif isinstance(group_key_input, list):
            group_key_list = [str(k).strip() for k in group_key_input if str(k).strip()]
        else:
            group_key_list = []

        result = call_system_connections_get(group_key=group_key_list, client_register=client_register_uuids)
        return jsonify({"statusCode": 200, "message": "System connections retrieved", "data": result})
    except Exception as e:
        Log.error(f"[Auth] System Connections Get failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@auth_bp.route('/api/auth/client-registers/revoke-api-key', methods=['POST'])
@require_auth
def revoke_api_key():
    try:
        data = request.json
        system_id = data.get('system_id')
        password = data.get('password')
        user_id = g.user_id

        if not system_id or not password:
            return jsonify({"statusCode": 400, "message": "system_id and password are required"}), 400

        user_item = users_repo.find_by_id(user_id)
        if not user_item:
            return jsonify({"statusCode": 404, "message": "User not found"}), 404
        
        user_id_int = user_item.get("user_id")
        auth_record = auth_service_repo.collection.find_one({"user_id": user_id_int, "uuid": system_id})
        if not auth_record or not auth_record.get("key"):
            return jsonify({"statusCode": 404, "message": "No connection or API key found"}), 404

        result = call_revoke_api_key(system_id, auth_record.get("key"), password)
        if result and result.get("status") == "success":
            auth_service_repo.collection.delete_one({"_id": auth_record["_id"]})
            return jsonify({"statusCode": 200, "message": "API Key revoked successfully", "data": result})
        return jsonify({"statusCode": 400, "message": result.get("message", "Revocation failed"), "data": result}), 400
    except Exception as e:
        Log.error(f"[Auth] Revoke API Key failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@auth_bp.route('/api/auth/external-token', methods=['POST'])
def external_auth_token():
    try:
        data = request.json if request.is_json else request.form.to_dict()
        system_id = data.get("system_id")
        api_key = data.get("api_key")
        user_id = data.get("user_id")

        if not all([system_id, api_key, user_id]):
            return jsonify({"statusCode": 400, "message": "Missing system_id, api_key, user_id"}), 400

        response_data = call_auth_token(system_id, api_key, user_id)
        return jsonify(response_data), 200
    except Exception as e:
        Log.error(f"[Auth] External Token Error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@auth_bp.route('/api/auth/upload-document', methods=['POST'])
@require_auth
def upload_document_route():
    try:
        data = request.json
        request_user_id = data.get("user_id")
        system_id = data.get("system_id")
        payload = data.get("payload")
        
        if not all([request_user_id, system_id, payload]):
            return jsonify({"statusCode": 400, "message": "Missing user_id, system_id, payload"}), 400
        
        auth_record = auth_service_repo.collection.find_one({"user_id": request_user_id, "uuid": system_id})
        if not auth_record:
            return jsonify({"statusCode": 404, "message": "No connection found"}), 404
        
        endpoint = auth_record.get("endpoint")
        api_key = auth_record.get("key")
        
        result = upload_document(endpoint=endpoint, system_id=system_id, api_key=api_key, user_id=request_user_id, payload=payload)
        return jsonify(result), 200
    except Exception as e:
        Log.error(f"[Auth] Upload Document Error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── 3. LICENSE MANAGEMENT (ADMIN) ───────────────────────────────────────────

@auth_bp.route("/api/admin/license/register", methods=["POST"])
@require_auth
@require_role(0)
def admin_register_license():
    try:
        data = request.json or {}
        label = data.get("label")
        expired_at = data.get("expired_at")
        notes = data.get("notes", "")
        
        if not label or not expired_at:
            return jsonify({"statusCode": 400, "message": "label và expired_at là bắt buộc."}), 400
        
        from src.shared.services.auth_sdk_service import auth_sdk_service
        result = auth_sdk_service.register_license(label=label, expired_at=expired_at, notes=notes)
        return jsonify({"statusCode": 200, "message": "Đăng ký license thành công.", "data": result}), 200
    except Exception as e:
        Log.error(f"[Admin API] Đăng ký license thất bại: {e}")
        return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500


@auth_bp.route("/api/admin/license/verify", methods=["POST"])
@require_auth
@require_role(0)
def admin_verify_license():
    try:
        from src.shared.services.auth_sdk_service import auth_sdk_service
        result = auth_sdk_service.verify_license()
        return jsonify({"statusCode": 200, "message": "Xác thực và kích hoạt license thành công.", "data": result}), 200
    except Exception as e:
        Log.error(f"[Admin API] Xác thực license thất bại: {e}")
        return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500


@auth_bp.route("/api/admin/license/status", methods=["GET"])
@require_auth
@require_role(0)
def admin_license_status():
    try:
        latest = licenses_repo.find_latest()
        active = licenses_repo.find_active(datetime.now())
        
        for item in [latest, active]:
            if item:
                item["_id"] = str(item["_id"])
                for k in ["expired_at", "created_at", "updated_at", "verified_at"]:
                    if isinstance(item.get(k), datetime):
                        item[k] = item[k].isoformat() + "Z"

        return jsonify({"statusCode": 200, "data": {"latest": latest, "active": active}}), 200
    except Exception as e:
        Log.error(f"[Admin API] Lấy trạng thái license thất bại: {e}")
        return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500
