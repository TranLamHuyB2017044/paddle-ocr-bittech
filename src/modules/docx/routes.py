"""
Docx Module Routes
Concentrated router for Docx document operations, User Profile, Authentication, Subscriptions, Sheet & Email integrations.
"""
import os
import json
import time
import traceback
import tempfile
from datetime import datetime

from flask import Blueprint, request, jsonify, g
from werkzeug.utils import secure_filename
from google.oauth2.credentials import Credentials
import cloudinary
import cloudinary.uploader

from src.shared.utils.auth_middleware import require_auth, require_role
from src.shared.utils.logger import Log
from src.shared.utils.rate_limit import get_limiter, limiter
from src.shared.utils.file_utils import validate_image_file
from src.shared.utils.security import hash_token
from src.shared.services.auth_service_mongo import auth_service
from src.shared.services.oauth_service import oauth_service, DRIVE_SCOPES
from src.shared.services.token_service import token_service
from src.shared.services.email_service import email_service
from src.shared.services.subscription_service import subscription_service
from src.shared.repositories.users_repository import users_repo
from src.shared.repositories.accounts_repository import accounts_repo
from src.shared.repositories.documents_repository import documents_repo
from src.shared.repositories.subscription_logs_repository import sub_logs_repo
from src.shared.repositories.extraction_logs_repository import extraction_logs_repo
from src.shared.repositories.extraction_reports_repository import extraction_reports_repo
from src.shared.repositories.corrections_repository import corrections_repo
from src.shared.repositories.chatbot_repository import chatbot_repo
from src.shared.extractors.openai_extractor import openai_extractor
import src.core.config as config
from src.core.config import PLANS_CONFIG, ALLOWED_IMAGE_EXTENSIONS

docx_bp = Blueprint("docx_bp", __name__)
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB


# ── 1. STATS, EXTRACTIONS & CORRECTIONS ───────────────────────────────────────

@docx_bp.route("/api/stats", methods=["GET"])
@require_auth
def get_user_stats():
    try:
        user_id = getattr(g, 'user_id', None)
        if not user_id:
            return jsonify({"statusCode": 401, "message": "User not authenticated"}), 401
        
        user_data = users_repo.find_by_id(user_id)
        if not user_data:
            return jsonify({"statusCode": 404, "message": "User not found"}), 404
        
        stats = user_data.get("stats", {})
        total_extractions = stats.get("total_extractions", 0)
        last_extraction_at = stats.get("last_extraction_at")
        doc_type_stats = stats.get("doc_type_stats", {})
        
        breakdown = {
            "idCard": doc_type_stats.get("idCard", 0),
            "driverLicense": doc_type_stats.get("driverLicense", 0),
            "invoice": doc_type_stats.get("invoice", 0),
            "document": doc_type_stats.get("document", 0),
            "vehicleDocuments": doc_type_stats.get("vehicleDocuments", 0) + doc_type_stats.get("vehicle_documents", 0),
            "vehicle": doc_type_stats.get("vehicleDocuments", 0) + doc_type_stats.get("vehicle_documents", 0)
        }
        
        today_extractions = extraction_logs_repo.count_today_by_user(user_id)
        managed_members_count = 0
        query_user_ids = [user_data.get("_id")]
        
        role = user_data.get("role", 2)
        account_id = user_data.get("account_id")
        
        if role == 0:
            query_user_ids = None
            managed_members_count = users_repo.collection.count_documents({})
        elif role == 1 and account_id:
            team_members = list(users_repo.collection.find({"account_id": account_id}, {"_id": 1, "role": 1}))
            managed_members_count = sum(1 for m in team_members if m.get("role") == 2)
            query_user_ids = [m["_id"] for m in team_members]

        recent_extractions = extraction_logs_repo.get_recent_extractions(query_user_ids, limit=5)

        return jsonify({
            "statusCode": 200,
            "message": "Success",
            "data": {
                "total_extractions": total_extractions,
                "today_extractions": today_extractions,
                "last_extraction_at": last_extraction_at.isoformat() if last_extraction_at else None,
                "breakdown": breakdown,
                "doc_type_stats": breakdown,
                "recent_extractions": recent_extractions,
                "managed_members": managed_members_count
            }
        }), 200
    except Exception as e:
        Log.error(f"[DocxAPI] Error fetching user stats: {e}")
        return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500


@docx_bp.route("/api/extractions", methods=["GET"])
@require_auth
def get_user_extractions():
    try:
        user_id = getattr(g, 'user_id', None)
        if not user_id:
            return jsonify({"statusCode": 401, "message": "User not authenticated"}), 401
        
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 10, type=int)
        doc_type = request.args.get('document_type')
        
        result = extraction_logs_repo.get_paginated_extractions(user_id, page=page, limit=limit, doc_type=doc_type)
        return jsonify({
            "statusCode": 200,
            "message": "Success",
            "data": result
        }), 200
    except Exception as e:
        Log.error(f"[DocxAPI] Error fetching paginated extractions: {e}")
        return jsonify({"statusCode": 500, "message": "Internal server error", "error": str(e)}), 500


@docx_bp.route("/api/corrections/submit", methods=["POST"])
@require_auth
def submit_correction():
    try:
        data = request.json
        doc_id = data.get("document_id")
        corrected_data = data.get("corrected_data")

        if not doc_id or not corrected_data:
            return jsonify({"statusCode": 400, "message": "Missing document_id or corrected_data"}), 400

        doc = documents_repo.find_by_id(doc_id)
        if not doc:
            return jsonify({"statusCode": 404, "message": "Document not found"}), 404
        
        old_result = doc.get("result", {})
        doc_type = doc.get("document_type", "unknown")
        user_id = getattr(g, 'user_id', None)

        def track_diff(obj1, obj2, prefix=""):
            if not isinstance(obj1, dict) or not isinstance(obj2, dict):
                return
            
            for key, val2 in obj2.items():
                val1 = obj1.get(key)
                field_path = f"{prefix}.{key}" if prefix else key
                
                if isinstance(val2, list) and isinstance(val1, list):
                    for i, (item1, item2) in enumerate(zip(val1, val2)):
                        track_diff(item1, item2, f"{field_path}[{i}]")
                elif val1 != val2 and val2 is not None:
                    corrections_repo.log_correction(
                        doc_type=doc_type,
                        field_name=field_path,
                        original_text=val1,
                        corrected_text=val2,
                        user_id=user_id
                    )

        track_diff(old_result, corrected_data)
        documents_repo.update_status(doc_id, status=doc.get("status"), result=corrected_data)

        return jsonify({
            "statusCode": 200,
            "message": "Correction submitted and learned successfully"
        }), 200

    except Exception as e:
        Log.error(f"[DocxAPI] Correction Error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@docx_bp.route("/api/report_extraction", methods=["POST"])
@require_auth
def report_extraction():
    try:
        data = request.json
        doc_id = data.get("document_id")
        reason = data.get("reason")
        details = data.get("details")
        extraction_result = data.get("extraction_result")

        if not doc_id or not reason:
            return jsonify({"statusCode": 400, "message": "Missing document_id or reason"}), 400

        user_id = getattr(g, 'user_id', None)
        doc_type = None
        try:
            doc_info = documents_repo.find_by_id(doc_id)
            if doc_info:
                doc_type = doc_info.get("document_type")
        except:
            pass
        
        report_id = extraction_reports_repo.create_report(
            document_id=doc_id,
            user_id=user_id,
            reason=reason,
            details=details,
            extraction_result=extraction_result,
            doc_type=doc_type
        )
        
        extraction_logs_repo.update_report(doc_id, reason, details, extraction_result)
        Log.info(f"[DocxAPI] Report created: {report_id} for document: {doc_id}")
        
        return jsonify({
            "statusCode": 200, 
            "message": "Report submitted successfully",
            "data": {"report_id": report_id}
        }), 200

    except Exception as e:
        Log.error(f"[DocxAPI] Report Error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── 2. AUTHENTICATION & USER MANAGEMENT ─────────────────────────────────────

@docx_bp.route('/api/user/update-user-avatar', methods=['PUT'])
@require_auth
def update_user_avatar():
    try:
        if 'avatar' not in request.files:
            return jsonify({"statusCode": 400, "message": "Không tìm thấy file ảnh tải lên. (Key: 'avatar')"}), 400
        
        file = request.files['avatar']
        if file.filename == '':
            return jsonify({"statusCode": 400, "message": "Bạn chưa chọn file nào."}), 400
            
        is_valid, reason = validate_image_file(file, file.filename)
        if not is_valid:
            return jsonify({"statusCode": 400, "message": reason}), 400

        file.seek(0, 2)
        if file.tell() > MAX_FILE_SIZE:
            return jsonify({"statusCode": 400, "message": "Kích thước ảnh không được vượt quá 5MB."}), 400
        file.seek(0)
        
        try:
            upload_result = cloudinary.uploader.upload(
                file, 
                folder="user_avatars",
                overwrite=True,
                resource_type="image"
            )
        except Exception as cloud_err:
            Log.error(f"[DocxAPI] Cloudinary upload failed: {cloud_err}")
            return jsonify({"statusCode": 500, "message": "Lỗi upload ảnh lên Cloudinary server."}), 500
             
        avatar_url = upload_result.get('secure_url')
        success = users_repo.update(g.user_id, {
            "avatar_url": avatar_url, 
            "updated_at": datetime.now()
        })
        
        if success:
            return jsonify({
                "statusCode": 200, 
                "message": "Cập nhật ảnh đại diện thành công", 
                "data": {"avatar_url": avatar_url}
            }), 200
        else:
            return jsonify({"statusCode": 400, "message": "Đã có lỗi khi lưu dữ liệu vào cơ sở dữ liệu."}), 400
             
    except Exception as e:
        Log.error(f"[DocxAPI] Update avatar failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@docx_bp.route('/api/user/update', methods=['PUT'])
@require_auth
def update_profile():
    try:
        data = request.json
        allowed_fields = ["fullname", "phone", "avatar_url", "group_key", "user_id", "role"]
        update_data = {k: v for k, v in data.items() if k in allowed_fields}
        
        if not update_data:
            return jsonify({"statusCode": 400, "message": "No valid fields to update"}), 400

        success = users_repo.update(g.user_id, update_data)
        if success:
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
        Log.error(f"[DocxAPI] Update failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@docx_bp.route('/api/auth/register', methods=['POST'])
@limiter.limit("5 per minute")
def register():
    try:
        data = request.json
        username = data.get('username')
        email = data.get('email')
        password = data.get('password')
        fullname = data.get('fullname')
        phone = data.get('phone')
        role = data.get('role', 2)
        account_id = data.get('account_id')
        plan = data.get('plan')

        api_key = request.headers.get("x-api-key")
        if api_key:
            try:
                clean_key = api_key[3:] if api_key.startswith("ak_") else api_key
                if "." in clean_key:
                    access_key, plain_secret = clean_key.split(".", 1)
                    creator = users_repo.find_by_api_key_access(access_key)
                    if creator and creator.get("api_key"):
                        stored_hash = creator["api_key"]["hashed_secret"]
                        input_hash = hash_token(plain_secret)
                        if input_hash == stored_hash:
                            creator_role = creator.get('role', 2)
                            if creator_role == 1:
                                can_create, msg = subscription_service.can_create_user(creator)
                                if not can_create:
                                    return jsonify({"statusCode": 403, "message": msg}), 403
                                role = 2
                                account_id = creator.get('account_id')
                                plan = None
                            if creator_role != 0:
                                plan = None
                                role = 2
            except Exception as e:
                Log.error(f"[DocxAPI] Register permission check failed: {e}")
        else:
            plan = None
            role = 2

        if not email or not password or not username:
            return jsonify({"statusCode": 400, "message": "Email, password and username are required"}), 400
            
        object_id, user_id_int = auth_service.register(username, email, password, fullname, phone, role=role, account_id=account_id, plan=plan)
        
        return jsonify({
            "statusCode": 201,
            "message": "User registered successfully",
            "data": {
                "id": str(object_id),
                "user_id": user_id_int,
                "created_plan": plan if not account_id else None
            }
        }), 201
    except ValueError as e:
        return jsonify({"statusCode": 400, "message": str(e)}), 400
    except Exception as e:
        Log.error(f"[DocxAPI] Register failed: {e}")
        return jsonify({"statusCode": 500, "message": "Internal Server Error"}), 500


@docx_bp.route('/api/admin/accounts/reset-quota', methods=['POST'])
@require_auth
@require_role(0)
def admin_reset_quota():
    data = request.json
    account_id = data.get('account_id')
    
    if not account_id:
        return jsonify({"statusCode": 400, "message": "account_id is required"}), 400
        
    success = accounts_repo.reset_quota(account_id)
    if success:
        return jsonify({"statusCode": 200, "message": f"Quota reset for account {account_id}"})
    return jsonify({"statusCode": 400, "message": "Reset failed"}), 400


@docx_bp.route('/api/admin/accounts/upgrade-plan', methods=['POST'])
@require_auth
@require_role(0)
def admin_upgrade_plan_account():
    data = request.json
    account_id = data.get('account_id')
    new_plan = data.get('plan')
    
    if not account_id or not new_plan:
        return jsonify({"statusCode": 400, "message": "account_id and plan are required"}), 400
        
    if new_plan not in PLANS_CONFIG:
        return jsonify({"statusCode": 400, "message": f"Invalid plan: {new_plan}"}), 400
        
    accounts_repo.update(account_id, {"plan": new_plan})
    accounts_repo.reset_quota(account_id)
    
    return jsonify({
        "statusCode": 200, 
        "message": f"Account {account_id} upgraded to {new_plan} and quota reset."
    })


@docx_bp.route('/api/auth/quota', methods=['GET'])
@require_auth
def get_quota():
    try:
        account_id = request.args.get('account_id')
        if account_id:
            if g.user.get('role') != 0:
                return jsonify({"statusCode": 403, "message": "Only admins can view other accounts"}), 403
        else:
            account_id = g.user.get('account_id')

        if not account_id:
            return jsonify({"statusCode": 404, "message": "No account associated with this user"}), 404
             
        quota_info = subscription_service.get_quota_info(account_id)
        return jsonify({"statusCode": 200, "data": quota_info})
    except Exception as e:
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@docx_bp.route('/api/admin/accounts', methods=['GET'])
@require_auth
@require_role(0)
def admin_get_accounts():
    accounts = list(accounts_repo.collection.find().limit(100))
    for acc in accounts:
        acc['_id'] = str(acc['_id'])
        
    return jsonify({"statusCode": 200, "data": accounts})


@docx_bp.route('/api/admin/users', methods=['GET'])
@require_auth
@require_role(0)
def admin_get_users():
    role_param = request.args.get('role')
    query = {}
    if role_param is not None:
        try:
            query["role"] = int(role_param)
        except ValueError:
            pass
    
    users = list(users_repo.collection.find(query).limit(100))
    for user in users:
        user['_id'] = str(user['_id'])
        user.pop("password", None)
        if user.get("account_id"):
            user["account_id"] = str(user["account_id"])
        
    return jsonify({"statusCode": 200, "data": users})


@docx_bp.route('/api/auth/login', methods=['POST'])
@limiter.limit("10 per minute")
def login():
    try:
        data = request.json
        username = data.get('username')
        password = data.get('password')
        is_dev = data.get('isDev', False)
        
        if not username or not password:
            return jsonify({"statusCode": 400, "message": "Username and password are required"}), 400
            
        user_agent = request.headers.get('User-Agent', 'Unknown')
        device_id = request.headers.get('X-Device-ID')
        
        if not is_dev and not device_id:
            return jsonify({"statusCode": 400, "message": "Device ID is required"}), 400
            
        ip = request.remote_addr
        result = auth_service.login(username, password, user_agent, ip, device_id, is_dev=is_dev)
        
        return jsonify({"statusCode": 200, "message": "Login successful", "data": result})
    except ValueError as e:
        return jsonify({"statusCode": 401, "message": str(e)}), 401
    except Exception as e:
        Log.error(f"[DocxAPI] Login failed: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@docx_bp.route('/api/auth/refresh', methods=['POST'])
def refresh():
    try:
        data = request.json
        refresh_token = data.get('refresh_token')
        
        if not refresh_token:
            return jsonify({"statusCode": 400, "message": "Refresh token is required"}), 400
            
        result = auth_service.reduce_refresh_token(refresh_token)
        return jsonify({"statusCode": 200, "message": "Token refreshed", "data": result})
    except ValueError as e:
        return jsonify({"statusCode": 401, "message": str(e)}), 401
    except Exception as e:
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@docx_bp.route('/api/auth/logout', methods=['POST'])
def logout():
    try:
        data = request.json
        refresh_token = data.get('refresh_token')
        if refresh_token:
            auth_service.logout(refresh_token)
            
        return jsonify({"statusCode": 200, "message": "Logged out successfully"})
    except Exception as e:
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@docx_bp.route('/api/auth/me', methods=['GET'])
@require_auth
def get_me():
    try:
        user = users_repo.find_by_id(g.user_id)
        if not user:
            return jsonify({"statusCode": 404, "message": "User not found"}), 404
             
        user.pop("password", None)
        user["_id"] = str(user["_id"])
        
        chatbots = []
        account_id = user.get("account_id")
        if account_id:
            chatbots = chatbot_repo.find_by_account_id(str(account_id))
            chatbots = [
                {
                    "id": str(cb["_id"]),
                    "name": cb.get("name"),
                    "description": cb.get("description"),
                    "avatar_url": cb.get("avatar_url"),
                    "public_token": cb.get("public_token")
                }
                for cb in chatbots
            ]
        
        user["chatbots"] = chatbots
        return jsonify({"statusCode": 200, "data": user})
    except Exception as e:
        Log.error(f"[DocxAPI] get_me error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── 3. EMAIL & GOOGLE SHEETS INTEGRATIONS ────────────────────────────────────

@docx_bp.route('/send-email', methods=['POST'])
@require_auth
def send_email():
    try:
        data = request.get_json()
        subject = data.get('subject')
        body = data.get('body')
        email_service.send_email(subject, body)
        return jsonify({'message': 'Email sent successfully'})
    except Exception as e:
        return jsonify({'message': 'Failed to send email', 'error': str(e)}), 500


@docx_bp.route('/api/save-to-sheet', methods=['POST'])
def save_to_sheet():
    try:
        data = request.json
        ocr_data = data.get("data")
        doc_type = data.get("doc_type", "document")
        email = data.get("email")
        token = None
        
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            if not email:
                try:
                    user_info = oauth_service.get_user_info_from_token(token)
                    email = user_info.get("email")
                except:
                    pass

        if not email:
            return jsonify({"statusCode": 400, "message": "Missing email or valid token"}), 400

        creds = None
        stored_tokens = token_service.get_user_tokens(email)
        if stored_tokens:
            creds = Credentials(
                token=stored_tokens.get("token"),
                refresh_token=stored_tokens.get("refresh_token"),
                token_uri=stored_tokens.get("token_uri"),
                client_id=stored_tokens.get("client_id"),
                client_secret=stored_tokens.get("client_secret"),
                scopes=stored_tokens.get("scopes")
            )
        
        if not creds:
            return jsonify({
                "statusCode": 403, 
                "message": "User has not connected Drive. Please link your Google Drive account first."
            }), 403

        sheet_info = oauth_service.get_or_create_sheet(creds, email, doc_type)
        spreadsheet_id = sheet_info['spreadsheet_id']
        sheet_url = sheet_info['sheet_url']
        
        updated_cells = oauth_service.append_data(creds, spreadsheet_id, ocr_data, doc_type)
        
        document_id = data.get("document_id")
        if document_id:
            try:
                config = oauth_service.doc_config.get(doc_type, oauth_service.doc_config["default"])
                current_sheet_name = config.get("sheet_name")
                documents_repo.update(document_id, {
                    "sheet": {
                        "sheet_id": spreadsheet_id,
                        "sheet_url": sheet_url,
                        "sheet_name": current_sheet_name
                    }
                })
            except Exception as update_e:
                Log.error(f"[DocxAPI] Failed to update document {document_id}: {update_e}")

        return jsonify({
            "statusCode": 200,
            "message": "Data saved successfully to User Drive",
            "data": {
                "spreadsheet_id": spreadsheet_id,
                "sheet_url": sheet_url,
                "updated_cells": updated_cells
            }
        })
    except Exception as e:
        Log.error(f"[DocxAPI] save_to_sheet error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


# ── 4. SUBSCRIPTION & BILLING ────────────────────────────────────────────────

@docx_bp.route('/api/subscription/me', methods=['GET'])
@require_auth
def get_my_usage():
    try:
        if not g.user:
            return jsonify({"statusCode": 401, "message": "User context missing"}), 401

        account_id = g.user.get('account_id')
        if not account_id:
            return jsonify({"statusCode": 404, "message": "No account associated with user"}), 404

        quota_info = subscription_service.get_quota_info(account_id)
        if not quota_info:
            return jsonify({"statusCode": 404, "message": "Account not found"}), 404

        role_map = {0: "Admin", 1: "Manager", 2: "User"}
        user_role = g.user.get('role', 2)
        quota_info["user_role"] = user_role
        quota_info["user_role_name"] = role_map.get(user_role, "Unknown")

        return jsonify({"statusCode": 200, "data": quota_info}), 200
    except Exception as e:
        Log.error(f"[DocxAPI] get_my_usage error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@docx_bp.route('/api/subscription/manager/users-usage', methods=['GET'])
@require_auth
@require_role([0, 1])
def get_manager_sub_users_usage():
    try:
        current_user = g.user
        target_account_id = current_user.get('account_id')
        
        if current_user.get('role') == 0:
            requested_account_id = request.args.get('account_id')
            if requested_account_id:
                target_account_id = requested_account_id

        if not target_account_id:
            return jsonify({"statusCode": 400, "message": "Account ID mismatch"}), 400

        users = list(users_repo.collection.find(
            {"account_id": str(target_account_id)},
            {"password": 0, "api_key": 0}
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
        Log.error(f"[DocxAPI] get_manager_sub_users_usage error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@docx_bp.route('/api/subscription/cancel', methods=['POST'])
@require_auth
def cancel_subscription():
    try:
        if not g.user:
            return jsonify({"statusCode": 401, "message": "User context missing"}), 401

        account_id = g.user.get('account_id')
        if not account_id:
            return jsonify({"statusCode": 404, "message": "No account associated with user"}), 404

        account = accounts_repo.find_by_id(account_id)
        from_plan = account.get('plan', 0) if account else 0

        success = accounts_repo.update(account_id, {"plan": 0})
        
        if success:
            sub_logs_repo.log_action(
                actor_id=g.user_id,
                target_account_id=account_id,
                action="cancel",
                from_plan=from_plan,
                to_plan=0,
                details=f"User {g.user.get('username')} cancelled their own subscription"
            )

            return jsonify({
                "statusCode": 200,
                "message": "Đã hủy gói dịch vụ thành công. Tài khoản của bạn đã được chuyển về gói Free.",
                "data": {"account_id": str(account_id), "new_plan": 0}
            }), 200
        else:
            return jsonify({"statusCode": 400, "message": "Không thể hủy gói vào lúc này."}), 400

    except Exception as e:
        Log.error(f"[DocxAPI] cancel_subscription error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@docx_bp.route('/api/subscription/admin/overview', methods=['GET'])
@require_auth
@require_role(0)
def get_admin_overview():
    try:
        accounts = list(accounts_repo.collection.find())
        overview = []
        role_map = {0: "Admin", 1: "Manager", 2: "User"}
        for acc in accounts:
            acc_id = str(acc.get('_id'))
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

        return jsonify({"statusCode": 200, "data": overview}), 200

    except Exception as e:
        Log.error(f"[DocxAPI] get_admin_overview error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@docx_bp.route('/api/subscription/plans', methods=['GET'])
def get_plans():
    plans_list = []
    for plan_id, config in PLANS_CONFIG.items():
        plans_list.append({"id": plan_id, **config})
        
    return jsonify({"statusCode": 200, "data": plans_list}), 200


@docx_bp.route('/api/subscription/admin/upgrade-plan', methods=['POST'])
@require_auth
@require_role(0)
def admin_upgrade_plan_subscription():
    try:
        data = request.json
        user_id_int = data.get('user_id')
        account_id = data.get('account_id')
        new_plan = data.get('plan')
        target_account_id = account_id
        
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

        account = accounts_repo.find_by_id(target_account_id)
        if not account:
            return jsonify({"statusCode": 404, "message": "Account not found"}), 404

        final_plan = new_plan if new_plan is not None else account.get('plan', 0)

        if final_plan == 0:
            return jsonify({"statusCode": 400, "message": "Gói Free không được phép gia hạn hoặc làm mới lượt dùng."}), 400

        if final_plan not in PLANS_CONFIG:
            return jsonify({"statusCode": 400, "message": f"Invalid plan ID: {final_plan}"}), 400

        from_plan = account.get('plan', 0)
        success = accounts_repo.update(target_account_id, {"plan": final_plan})
        
        if success:
            accounts_repo.reset_quota(target_account_id)
            action = "upgraded" if new_plan is not None else "renewed"
            
            sub_logs_repo.log_action(
                actor_id=g.user_id,
                target_account_id=target_account_id,
                action=action,
                from_plan=from_plan,
                to_plan=final_plan,
                details=f"Admin {g.user.get('username')} {action} account"
            )

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
        Log.error(f"[DocxAPI] admin_upgrade_plan error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@docx_bp.route('/api/subscription/admin/reset-account', methods=['POST'])
@require_auth
@require_role(0)
def admin_reset_account():
    try:
        data = request.json
        user_id_int = data.get('user_id')
        account_id = data.get('account_id')
        target_account_id = account_id
        
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

        account = accounts_repo.find_by_id(target_account_id)
        if not account:
            return jsonify({"statusCode": 404, "message": "Account not found"}), 404

        from_plan = account.get('plan', 0)
        success = accounts_repo.update(target_account_id, {"plan": 0})
        
        if success:
            accounts_repo.reset_quota(target_account_id)
            sub_logs_repo.log_action(
                actor_id=g.user_id,
                target_account_id=target_account_id,
                action="reset",
                from_plan=from_plan,
                to_plan=0,
                details=f"Admin {g.user.get('username')} force reset account to Free"
            )

            return jsonify({
                "statusCode": 200,
                "message": "Account reset to Free plan with 0 usage.",
                "data": {"account_id": str(target_account_id), "new_plan": 0}
            }), 200
        else:
            return jsonify({"statusCode": 400, "message": "Failed to reset account"}), 400

    except Exception as e:
        Log.error(f"[DocxAPI] admin_reset_account error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@docx_bp.route("/api/analyze-message", methods=["POST"])
@require_auth
def handle_analyze_message():
    try:
        data = request.json
        message = data.get("message")
        sender_name = data.get("sender_name")

        if not message:
            return jsonify({"statusCode": 400, "message": "Missing 'message' in request body"}), 400

        result = openai_extractor.analyze_message(message, sender_name=sender_name)
        
        return jsonify({
            "statusCode": 200,
            "message": "Success",
            "data": result.get("data", {})
        }), 200

    except Exception as e:
        Log.error(f"[DocxAPI] Analyze Message Error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500
