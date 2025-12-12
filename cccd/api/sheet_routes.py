
from flask import Blueprint, request, jsonify
from cccd.services.google_sheets import google_sheet_service
from cccd.services.oauth_service import oauth_service
from cccd.utils.logger import Log

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

        # 1. Attempt to get Email from Token (Authorization Header)
        email = None
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ")[1]
            try:
                user_info = oauth_service.get_user_info_from_token(token)
                email = user_info.get("email")
                Log.info(f"[API] 🔑 Authenticated via Token: {email}")
            except Exception as e:
                Log.warning(f"[API] ⚠️ Invalid Token provided: {e}")

        # 2. Fallback to Body Email
        if not email:
            email = data.get("email")
        
        if not email or not ocr_data:
            return jsonify({"statusCode": 400, "message": "Missing email or data (requires Auth Token or 'email' in body)"}), 400

        # Delegate to service
        # 1. Get or Create Sheet
        spreadsheet_id = google_sheet_service.get_or_create_sheet(email)
        
        # 2. Append Data
        google_sheet_service.append_data(spreadsheet_id, ocr_data, doc_type)
        
        sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        
        return jsonify({
            "statusCode": 200,
            "message": "Data saved successfully",
            "data": {
                "sheet_url": sheet_url,
                "spreadsheet_id": spreadsheet_id
            }
        })

    except Exception as e:
        Log.error(f"[API] ❌ Failed to save to sheet: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@sheet_bp.route('/api/update-sheet', methods=['POST'])
def update_sheet():
    """
    Test Route: Updates an existing sheet directly by ID.
    Body:
    {
        "spreadsheet_id": "1A2B3C...",
        "doc_type": "idCard",
        "data": { ... }
    }
    """
    try:
        data = request.json
        spreadsheet_id = data.get("spreadsheet_id")
        ocr_data = data.get("data")
        doc_type = data.get("doc_type", "document")
        
        if not spreadsheet_id or not ocr_data:
            return jsonify({"statusCode": 400, "message": "Missing spreadsheet_id or data"}), 400

        # Delegate to service: Append Data Directly
        updated_cells = google_sheet_service.append_data(spreadsheet_id, ocr_data, doc_type)
        
        sheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        
        return jsonify({
            "statusCode": 200,
            "message": "Sheet updated successfully",
            "data": {
                "sheet_url": sheet_url,
                "updated_cells": updated_cells
            }
        })

    except Exception as e:
        Log.error(f"[API] ❌ Failed to update sheet: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500
