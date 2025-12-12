
import os
import json
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from cccd.utils.logger import Log

# Path to your client_secret.json (User must provide this)
CLIENT_SECRETS_FILE = "client_secret.json"

# Updates these scopes to allow driving file creation
SCOPES = [
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid"
]

class OAuthService:
    def __init__(self):
        self.base_sheet_name = "Document_Data_Storage"

    def exchange_code_for_credentials(self, auth_code, redirect_uri):
        
        if not os.path.exists(CLIENT_SECRETS_FILE):
             raise FileNotFoundError(f"Missing {CLIENT_SECRETS_FILE}. Please download it from Google Cloud Console.")

        try:
            # Log để debug redirect_uri mismatch
            Log.info(f"[OAuth] 🔄 Creating flow with redirect_uri: '{redirect_uri}'")
            
            # Tạo OAuth flow từ client_secret.json
            # Nếu redirect_uri là None hoặc rỗng, một số flow native có thể chấp nhận
            kwargs = {"scopes": SCOPES}
            if redirect_uri:
                kwargs["redirect_uri"] = redirect_uri

            flow = Flow.from_client_secrets_file(
                CLIENT_SECRETS_FILE,
                **kwargs
            )
            
            # Exchange authorization code → credentials
            Log.info(f"[OAuth] 🔄 Exchanging code for credentials...")
            flow.fetch_token(code=auth_code)
            credentials = flow.credentials
            
            Log.info(f"[OAuth] ✅ Successfully exchanged code for credentials")
            Log.info(f"[OAuth] 📝 Token expires in: {credentials.expiry if hasattr(credentials, 'expiry') else 'N/A'}")
            
            return credentials
            
        except Exception as e:
            Log.error(f"[OAuth] ❌ Failed to exchange code: {e}")
            Log.error(f"[OAuth] 💡 Hint: Check if redirect_uri '{redirect_uri}' is added to Google Cloud Console")
            raise e

    def get_user_info(self, credentials):
        """Fetches user profile info using the credentials."""
        try:
            service = build('oauth2', 'v2', credentials=credentials)
            user_info = service.userinfo().get().execute()
            return user_info
        except Exception as e:
            Log.error(f"[OAuth] ❌ Failed to get user info: {e}")
            raise e

    def get_user_info_from_token(self, token):
        """Fetches user profile info using an access token."""
        try:
            # Create simple credentials with just the token
            creds = Credentials(token=token)
            service = build('oauth2', 'v2', credentials=creds)
            user_info = service.userinfo().get().execute()
            return user_info
        except Exception as e:
            Log.error(f"[OAuth] ❌ Failed to get user info from token: {e}")
            raise e

    def get_or_create_sheet(self, credentials, user_email):
        """
        Checks if a sheet named {self.base_sheet_name} exists in the user's Drive.
        If not, creates it.
        Returns the spreadsheet ID and URL.
        """
        try:
            service = build('drive', 'v3', credentials=credentials)
            sheets_service = build('sheets', 'v4', credentials=credentials)

            # 1. Search for existing file
            query = f"name = '{self.base_sheet_name}' and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
            results = service.files().list(q=query, spaces='drive', fields='files(id, name, webViewLink)').execute()
            files = results.get('files', [])

            if files:
                # Found existing
                sheet = files[0]
                Log.info(f"[OAuth] ✅ Found existing sheet for {user_email}: {sheet['id']}")
                return {
                    "spreadsheet_id": sheet['id'],
                    "sheet_url": sheet['webViewLink'],
                    "is_new": False
                }
            else:
                # 2. Create new file
                sheet_metadata = {
                    'properties': {
                        'title': self.base_sheet_name
                    }
                }
                spreadsheet = sheets_service.spreadsheets().create(body=sheet_metadata, fields='spreadsheetId,spreadsheetUrl').execute()
                spreadsheet_id = spreadsheet.get('spreadsheetId')
                sheet_url = spreadsheet.get('spreadsheetUrl')
                
                # 3. Initialize Headers (Optional but recommended)
                self._init_header(sheets_service, spreadsheet_id)

                Log.info(f"[OAuth] 🆕 Created new sheet for {user_email}: {spreadsheet_id}")
                return {
                    "spreadsheet_id": spreadsheet_id,
                    "sheet_url": sheet_url,
                    "is_new": True
                }

        except Exception as e:
            Log.error(f"[OAuth] ❌ Error handling sheet for {user_email}: {e}")
            raise e

    def _init_header(self, sheets_service, spreadsheet_id):
        headers = ["Type", "Full Name", "ID Number", "DOB", "Address", "Hometown", "Date", "Created At"]
        body = {
            "values": [headers]
        }
        sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range="Sheet1!A1",
            valueInputOption="RAW",
            body=body
        ).execute()

oauth_service = OAuthService()
