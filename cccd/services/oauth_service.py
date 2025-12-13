
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
# Updates these scopes to allow driving file creation
SCOPES = [
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid"
]

# Separate scope list for Drive Connect as requested
DRIVE_SCOPES = SCOPES + [
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid",
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/spreadsheets',
]
drivescope = DRIVE_SCOPES

class OAuthService:
    def __init__(self):
        self.base_sheet_name = "Document_Data_Storage"

    def exchange_code_for_credentials(self, auth_code, redirect_uri, scopes=None):
        
        if not os.path.exists(CLIENT_SECRETS_FILE):
             raise FileNotFoundError(f"Missing {CLIENT_SECRETS_FILE}. Please download it from Google Cloud Console.")

        # Default to basic SCOPES if not provided
        target_scopes = scopes if scopes else SCOPES

        try:
            # Log để debug redirect_uri mismatch
            Log.info(f"[OAuth] 🔄 Creating flow with redirect_uri: '{redirect_uri}'")
            
            # Tạo OAuth flow từ client_secret.json
            # Nếu redirect_uri là None hoặc rỗng, một số flow native có thể chấp nhận
            kwargs = {"scopes": target_scopes}
            if redirect_uri:
                kwargs["redirect_uri"] = redirect_uri

            # Check for Environment Variables first (Production)
            client_id = os.getenv("GOOGLE_CLIENT_ID")
            client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

            if client_id and client_secret:
                Log.info("[OAuth] 🌍 Loading Google Credentials from Environment Variables")
                client_config = {
                    "web": {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    }
                }
                project_id = os.getenv("GOOGLE_PROJECT_ID")
                if project_id:
                    client_config["web"]["project_id"] = project_id

                flow = Flow.from_client_config(
                    client_config,
                    **kwargs
                )
            elif os.path.exists(CLIENT_SECRETS_FILE):
                # Fallback to local file (Development)
                Log.info(f"[OAuth] 📂 Loading Google Credentials from {CLIENT_SECRETS_FILE}")
                flow = Flow.from_client_secrets_file(
                    CLIENT_SECRETS_FILE,
                    **kwargs
                )
            else:
                raise FileNotFoundError(
                    f"Missing {CLIENT_SECRETS_FILE} or GOOGLE_CLIENT_ID/SECRET env vars. "
                    "Please Configure Google OAuth credentials."
                )
            
            # Exchange authorization code → credentials
            Log.info(f"[OAuth] 🔄 Exchanging code for credentials...")
            flow.fetch_token(code=auth_code)
            credentials = flow.credentials
            
            Log.info(f"[OAuth] ✅ Successfully exchanged code for credentials")
            Log.info(f"[OAuth] 📝 Token expires in: {credentials.expiry if hasattr(credentials, 'expiry') else 'N/A'}")
            
            # Check for Drive permissions
            # Note: scopes might be a set or list.
            current_scopes = set(credentials.scopes) if credentials.scopes else set()
            drive_scope = "https://www.googleapis.com/auth/drive.file"
            sheet_scope = "https://www.googleapis.com/auth/spreadsheets"
            
            # Simple check: If they have drive OR sheet, we consider it "connected" for our purpose, 
            # though ideally we need both or just drive.
            has_drive = drive_scope in current_scopes and sheet_scope in current_scopes
            
            # Attach dynamic attribute to be used by caller
            credentials.has_drive_permissions = has_drive
            Log.info(f"[OAuth] 📂 Drive Permissions Granted: {has_drive}")
            
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
        headers = ["ID Number", "Full Name", "DOB", "Address", "Hometown", "Date of Issue", "Date of Expiry", "Place of Issue", "Created At"]
        body = {
            "values": [headers]
        }
        sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range="A1",
            valueInputOption="RAW",
            body=body
        ).execute()

    def append_data(self, credentials, spreadsheet_id, data, doc_type):
        """Appends a row of data using user credentials."""
        try:
            service = build('sheets', 'v4', credentials=credentials)
            
            # Normalize data based on doc_type (matching user schema)
            row = [
                data.get("idNumber", ""),
                data.get("fullName", ""),
                data.get("dob", ""),
                data.get("gender", ""),
                data.get("nationality", ""),
                data.get("address", ""),
                data.get("hometown", ""),
                data.get("dateOfIssue", ""),
                data.get("expiryDate", ""),
                data.get("placeOfIssue", "")
            ]
            
            # Add timestamp
            from datetime import datetime
            row.append(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

            body = {
                "values": [row]
            }

            result = service.spreadsheets().values().append(
                spreadsheetId=spreadsheet_id,
                range="A1",
                valueInputOption="USER_ENTERED",
                body=body
            ).execute()

            Log.info(f"[OAuth] 📝 Appended data to sheet {spreadsheet_id}")
            return result.get("updates", {}).get("updatedCells")

        except Exception as e:
            Log.error(f"[OAuth] ❌ Failed to append data: {e}")
            raise e

oauth_service = OAuthService()
