
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
        
        self.authenticate()

    def authenticate(self):
        """Authenticates using the service account file or environment variable."""
        try:
            # 1. Try Environment Variable (Production)
            sa_json = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
            if sa_json:
                try:
                    info = json.loads(sa_json)
                    self.creds = service_account.Credentials.from_service_account_info(
                        info, scopes=SCOPES
                    )
                    Log.info("[GoogleSheet] 🌍 Authenticated via GOOGLE_SERVICE_ACCOUNT_JSON Env Var")
                except json.JSONDecodeError:
                     Log.error("[GoogleSheet] ❌ Failed to parse GOOGLE_SERVICE_ACCOUNT_JSON")
            
            # 2. Try Local File (Development)
            elif os.path.exists(self.service_account_file):
                self.creds = service_account.Credentials.from_service_account_file(
                    self.service_account_file, scopes=SCOPES
                )
                Log.info(f"[GoogleSheet] 📂 Authenticated via File: {self.service_account_file}")
            
            else:
                Log.warning(f"[GoogleSheet] ⚠️ No service account credentials found ({self.service_account_file} or Env Var).")
                return

            if self.creds:
                self.sheets_service = build("sheets", "v4", credentials=self.creds)
                self.drive_service = build("drive", "v3", credentials=self.creds)
                Log.info("[GoogleSheet] ✅ Service initialized successfully.")

        except Exception as e:
            Log.error(f"[GoogleSheet] ❌ Authentication failed: {e}")

    def get_or_create_sheet(self, user_email):
        if not self.drive_service or not self.sheets_service:
            Log.error("[GoogleSheet] ❌ Service not authenticated.")
            return None

        sheet_title = f"OCR Data - {user_email}"

        # 1. Search for existing sheet by name
        try:
            query = f"name = '{sheet_title}' and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
            results = self.drive_service.files().list(q=query, spaces='drive', fields='files(id, name)').execute()
            files = results.get('files', [])

            if files:
                sheet_id = files[0]['id']
                Log.info(f"[GoogleSheet] ✅ Found existing sheet for {user_email}: {sheet_id}")
                return sheet_id

        except Exception as e:
            Log.error(f"[GoogleSheet] ⚠️ Error searching for files: {e}")
            # Continue to create if search fails? Or raise? Better to try creating.

        # 2. Create Sheet using Sheets API
        sheet_metadata = {
            'properties': {
                'title': sheet_title
            }
        }

        try:
            spreadsheet = self.sheets_service.spreadsheets().create(
                body=sheet_metadata,
                fields='spreadsheetId'
            ).execute()
            
            sheet_id = spreadsheet.get('spreadsheetId')
            Log.info(f"[GoogleSheet] 🆕 Created Sheet ID: {sheet_id}")

            # 3. Share with user
            self._share_file(sheet_id, user_email)
            
            # 4. Init header
            self._init_header(sheet_id)

            return sheet_id
        except Exception as e:
            Log.error(f"[GoogleSheet] ❌ Failed to create sheet: {e}")
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
