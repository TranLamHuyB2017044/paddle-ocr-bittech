
import os
import json
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from cccd.utils.logger import Log

# Scopes required
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]

class GoogleSheetService:
    def __init__(self, service_account_file="service_account.json"):
        self.service_account_file = service_account_file
        self.creds = None
        self.sheets_service = None
        self.drive_service = None
        
        # Simple JSON DB to map email -> sheet_id
        # Format: {"user@email.com": "spreadsheet_id"}
        self.db_file = "user_sheets_map.json"
        
        self.authenticate()

    def authenticate(self):
        """Authenticates using the service account file."""
        if not os.path.exists(self.service_account_file):
            Log.error(f"[GoogleSheet] ❌ Missing service account file: {self.service_account_file}")
            return

        try:
            self.creds = service_account.Credentials.from_service_account_file(
                self.service_account_file, scopes=SCOPES
            )
            self.sheets_service = build("sheets", "v4", credentials=self.creds)
            self.drive_service = build("drive", "v3", credentials=self.creds)
            Log.info("[GoogleSheet] ✅ Authenticated successfully.")
        except Exception as e:
            Log.error(f"[GoogleSheet] ❌ Authentication failed: {e}")

    def _load_db(self):
        if not os.path.exists(self.db_file):
            return {}
        try:
            with open(self.db_file, "r") as f:
                return json.load(f)
        except:
            return {}

    def _save_db(self, data):
        with open(self.db_file, "w") as f:
            json.dump(data, f, indent=2)

    def get_or_create_sheet(self, user_email):
        db = self._load_db()

        if user_email in db:
            return db[user_email]

        # 1. Create Sheet using Sheets API
        sheet_metadata = {
            'properties': {
                'title': f"OCR Data - {user_email}"
            }
        }

        try:
            spreadsheet = self.sheets_service.spreadsheets().create(
                body=sheet_metadata,
                fields='spreadsheetId'
            ).execute()
            
            sheet_id = spreadsheet.get('spreadsheetId')
            Log.info(f"[GoogleSheet] 🆕 Created Sheet ID: {sheet_id}")
        except Exception as e:
            Log.error(f"[GoogleSheet] ❌ Failed to create sheet: {e}")
            raise e

        # 2. Share with user
        self._share_file(sheet_id, user_email)
        
        # (Optional) Transfer ownership if needed, but service account must have permission
        # self._transfer_ownership(sheet_id, user_email)

        # 3. Init header
        self._init_header(sheet_id)

        # 4. Save mapping
        db[user_email] = sheet_id
        self._save_db(db)

        return sheet_id

    def _transfer_ownership(self, file_id, email):
        try:
            self.drive_service.permissions().create(
                fileId=file_id,
                body={
                    "role": "owner",
                    "type": "user",
                    "emailAddress": email
                },
                transferOwnership=True
            ).execute()
        except Exception as e:
            Log.error(f"[GoogleSheet] ⚠️ Failed to transfer ownership: {e}")
            raise e

    def _share_file(self, file_id, email):
        """Shares the file with the user's email as Editor."""
        try:
            body = {
                "role": "writer",
                "type": "user",
                "emailAddress": email
            }
            self.drive_service.permissions().create(
                fileId=file_id,
                body=body,
                fields="id"
            ).execute()
        except Exception as e:
            Log.error(f"[GoogleSheet] ⚠️ Failed to share sheet: {e}")
            raise e

    def _init_header(self, spreadsheet_id):
        """Writes the header row."""
        headers = ["ID Number", "Full Name",  "Date of Birth", "Gender", "Nationality", "Address", "Hometown", "Date of Issue", "Expiry Date", "Place of Issue"]
        body = {
            "values": [headers]
        }
        self.sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range="A1",
            valueInputOption="RAW",
            body=body
        ).execute()

    def append_data(self, spreadsheet_id, data, doc_type):
        """Appends a row of data."""
        # Normalize data based on doc_type (Simple mapping for now)
        
        # Common fields attempt
        row = [
            data.get("idNumber", ""),
            data.get("fullName", ""),
            data.get("dob", ""),
            data.get("gender", ""), 
            data.get("nationality", ""),
            data.get("hometown", ""), # Cần thêm field này vào nếu chưa có
            data.get("address", ""),
            data.get("dateOfIssue", ""),
            data.get("expiryDate", ""),
            data.get("placeOfIssue", "")
        ]
        
        body = {
            "values": [row]
        }
        
        result = self.sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range="A1",
            valueInputOption="USER_ENTERED", # Auto format date/numbers
            body=body
        ).execute()
        
        return result.get("updates", {}).get("updatedCells")

# Global Instance
google_sheet_service = GoogleSheetService()
