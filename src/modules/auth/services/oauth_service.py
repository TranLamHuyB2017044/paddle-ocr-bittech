
from typing import Any, Optional, cast
import os
import json
import google.auth.transport.requests
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from src.shared.utils.logger import Log
import src.core.config as config

# Path to your client_secret.json (User must provide this)
CLIENT_SECRETS_FILE = config.CLIENT_SECRETS_FILE

# Basic scopes for user info
SCOPES = [
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "openid"
]

# Extended scopes for Drive and Sheets access
DRIVE_SCOPES = SCOPES + [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/spreadsheets',
]

class OAuthService:
    def __init__(self):
        self.doc_config = {
            "idCard": {
                "sheet_name": "cccd_data",
                "headers": ["ID Number", "Full Name", "Ngày sinh", "Gender", "Nationality", "Address", "Hometown", "Date of Issue", "Date of Expiry", "Place of Issue", "Created At"],
                "fields": ["idNumber", "fullName", "dob", "gender", "nationality", "address", "hometown", "dateOfIssue", "expiryDate", "placeOfIssue"]
            },
            "invoice": {
                "sheet_name": "hoadon_data",
                "headers": ["Tên HĐ", "Số HĐ", "Ngày Lập", "Người Bán", "Địa Chỉ Bán", "Khách Hàng", "Địa Chỉ Mua", "Tổng Tiền", "Chi Tiết Sản Phẩm", "Created At"],
                "fields": ["invoiceName", "invoiceNumber", "invoiceDate", "sellerName", "sellerAddress", "customerName", "customerAddress", "totalAmount", "products"]
            },
            "driverLicense": {
                "sheet_name": "gplx_data",
                "headers": ["Số GPLX", "Họ tên", "Ngày sinh", "Quốc tịch", "Hạng", "Ngày hết hạn", "Ngày cấp", "Ngày trúng tuyển", "Created At"],
                "fields": ["idNumber", "fullName", "dob", "nationality", "rank", "expiryDate", "dateOfIssue", "dateOfBegining"]
            },
            "menu": {
                "sheet_name": "menu_data",
                "headers": ["Tên quán", "Thông tin chung", "Danh sách món ăn", "Created At"],
                "fields": ["business_name", "business_info", "menu_items"]
            },
            "administrativeDocument": {
                "sheet_name": "van_ban_den_data",
                "headers": ["Số/Ký hiệu", "Cơ quan ban hành", "Mã cơ quan", "Trích yếu", "Ngày ban hành", "Ngày nhận", "Hạn xử lý", "Độ khẩn", "Độ mật", "Lĩnh vực", "Yêu cầu phúc đáp", "Thời gian họp", "Ghi chú", "Created At"],
                "fields": ["documentNo", "senderOrg", "senderCode", "title", "issueDate", "receiveDate", "deadline", "priority", "security", "category", "requireReply", "meetingAt", "note"]
            },
            "default": {
                "sheet_name": "ocr_data",
                "headers": ["Raw Data", "Created At"],
                "fields": [] 
            }
        }

    def exchange_code_for_credentials(self, auth_code, redirect_uri, scopes=None):
        
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
            setattr(credentials, "has_drive_permissions", has_drive)
            Log.info(f"[OAuth] 📂 Drive Permissions Granted: {has_drive}")
            
            return credentials
            
        except Exception as e:
            Log.error(f"[OAuth] ❌ Failed to exchange code: {e}")
            Log.error(f"[OAuth] 💡 Hint: Check if redirect_uri '{redirect_uri}' is added to Google Cloud Console")
            raise e

    def get_user_info(self, credentials):
        """Fetches user profile info using the credentials."""
        try:
            service: Any = build('oauth2', 'v2', credentials=credentials)
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
            service: Any = build('oauth2', 'v2', credentials=creds)
            user_info = service.userinfo().get().execute()
            return user_info
        except Exception as e:
            Log.error(f"[OAuth] ❌ Failed to get user info from token: {e}")
            raise e

    def get_or_create_sheet(self, credentials, user_email, doc_type="idCard"):
        """
        Checks if a sheet for the given doc_type exists in the user's Drive.
        If not, creates it.
        Returns the spreadsheet ID and URL.
        """
        config = self.doc_config.get(doc_type, self.doc_config["default"])
        sheet_name = config["sheet_name"]
        
        try:
            service: Any = build('drive', 'v3', credentials=credentials)
            sheets_service: Any = build('sheets', 'v4', credentials=credentials)

            # 1. Search for existing file
            query = f"name = '{sheet_name}' and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
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
                        'title': sheet_name
                    }
                }
                spreadsheet = sheets_service.spreadsheets().create(body=sheet_metadata, fields='spreadsheetId,spreadsheetUrl').execute()
                spreadsheet_id = spreadsheet.get('spreadsheetId')
                sheet_url = spreadsheet.get('spreadsheetUrl')
                
                # 3. Initialize Headers (Optional but recommended)
                self._init_header(sheets_service, spreadsheet_id, config["headers"])

                Log.info(f"[OAuth] 🆕 Created new sheet for {user_email}: {spreadsheet_id} ({sheet_name})")
                return {
                    "spreadsheet_id": spreadsheet_id,
                    "sheet_url": sheet_url,
                    "is_new": True
                }

        except Exception as e:
            Log.error(f"[OAuth] ❌ Error handling sheet for {user_email}: {e}")
            raise e

    def _init_header(self, sheets_service, spreadsheet_id, headers):
        body = {
            "values": [headers]
        }
        sheets_service.spreadsheets().values().append(
            spreadsheetId=spreadsheet_id,
            range="A1",
            valueInputOption="RAW",
            body=body
        ).execute()

        # Update styling for header (Bold)
        requests = [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": 0,
                        "startRowIndex": 0,
                        "endRowIndex": 1
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "textFormat": {
                                "bold": True,
                                "fontSize": 11
                            },
                             "backgroundColor": {
                                "red": 0.9,
                                "green": 0.9,
                                "blue": 0.9
                            }
                        }
                    },
                    "fields": "userEnteredFormat(textFormat,backgroundColor)"
                }
            }
        ]

        sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests}
        ).execute()

    def append_data(self, credentials, spreadsheet_id, data, doc_type):
        """Appends a row of data using user credentials."""
        try:
            service: Any = build('sheets', 'v4', credentials=credentials)
            
            # Log keys for debugging
            Log.info(f"[OAuth] 🔍 Received Data Keys for {doc_type}: {list(data.keys())}")

            config = self.doc_config.get(doc_type, self.doc_config["default"])
            fields = config["fields"]
            
            # Normalize data based on doc_type
            row = []
            if doc_type == "default":
                 row.append(str(data))
            else:
                for field in fields:
                    # Generic lookup: try exact match, then conversion?
                    # Field in config is typically snake_case for invoice (e.g. ten_hoa_don)
                    # But input might be camelCase (e.g. tenHoaDon) or other.
                    
                    val = data.get(field)
                    
                    # Try camelCase alternative if snake_case missing
                    if val is None and "_" in field:
                        # Convert ten_hoa_don -> tenHoaDon
                        components = field.split('_')
                        camel_field = components[0] + ''.join(x.title() for x in components[1:])
                        val = data.get(camel_field)
                    
                    # Fallback for product list if strict key match failed
                    if val is None and field in ["lineItems", "danh_sach_san_pham"]:
                        # Try common variations
                        val = data.get("lineItems") or data.get("items") or data.get("danh_sach_san_pham") or data.get("products")
                    
                    if val is None: val = ""
                    
                    # Handle separate list for product list
                    if isinstance(val, list):
                        val = "\n".join(map(str, val))
                    
                    row.append(str(val))
            
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
