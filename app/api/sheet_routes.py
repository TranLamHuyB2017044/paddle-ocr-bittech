
from flask import Blueprint, request, jsonify
from app.services.oauth_service import oauth_service, drivescope
from app.services.token_service import token_service
from app.utils.logger import Log
from google.oauth2.credentials import Credentials

sheet_bp = Blueprint('sheet_bp', __name__)

@sheet_bp.route('/api/save-to-sheet', methods=['POST'])
def save_to_sheet():
    """
    Saves extracted data to the user's Google Sheet.
    Body:
    {
        "email": "user@gmail.com",
        "doc_type": "idCard",
        "data": { ... }
    }
    """
    try:
        data = request.json
        ocr_data = data.get("data")
        doc_type = data.get("doc_type", "document")
        
        email = data.get("email")
        token = None
        
        # 1. Check Authorization Header (Preferred)
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            # Try to get email from token if not provided in body
            if not email:
                try:
                    user_info = oauth_service.get_user_info_from_token(token)
                    email = user_info.get("email")
                except:
                    pass

        if not email:
             return jsonify({"statusCode": 400, "message": "Missing email or valid token"}), 400

        # 2. Reconstruct Credentials (Prioritize Stored Drive Tokens)
        creds = None
        
        # Look up stored Drive tokens for this user
        stored_tokens = token_service.get_user_tokens(email)
        if stored_tokens:
            Log.info(f"[API] 🔄 Found stored tokens for {email}")
            creds = Credentials(
                token=stored_tokens.get("token"),
                refresh_token=stored_tokens.get("refresh_token"),
                token_uri=stored_tokens.get("token_uri"),
                client_id=stored_tokens.get("client_id"),
                client_secret=stored_tokens.get("client_secret"),
                scopes=stored_tokens.get("scopes")
            )
        else:
             Log.warning(f"[API] ⚠️ No stored Drive tokens found for {email}")
        
        if not creds:
             return jsonify({
                 "statusCode": 403, 
                 "message": "User has not connected Drive. Please link your Google Drive account first."
             }), 403

        # 3. Perform Actions using User Credentials
        # Get/Create Sheet
        sheet_info = oauth_service.get_or_create_sheet(creds, email, doc_type)
        spreadsheet_id = sheet_info['spreadsheet_id']
        sheet_url = sheet_info['sheet_url']
        
        # Append Data
        updated_cells = oauth_service.append_data(creds, spreadsheet_id, ocr_data, doc_type)
        
        return jsonify({
            "statusCode": 200,
            "message": "Data saved successfully to User Drive",
            "data": {
                "sheet_url": sheet_url,
                "spreadsheet_id": spreadsheet_id,
                "updated_cells": updated_cells
            }
        })

    except Exception as e:
        Log.error(f"[API] ❌ Failed to save to sheet: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


