import os
from bittech_auth import AuthServiceClient, HttpxTransport, AuthService
from src.repositories.licenses_repository import licenses_repo
from src.repositories.auth_audit_repository import auth_audit_repo
import src.config as config

# 1. Khởi tạo transport và client
transport = HttpxTransport()

# Lấy đường dẫn tuyệt đối của license config để đảm bảo định vị chính xác
license_path = os.path.abspath(config.LICENSE_CONFIG_PATH)

client = AuthServiceClient(
    auth_api_url=config.AUTH_API_URL,
    system_id=config.SYSTEM_ID,
    license_config_path=license_path,
    transport=transport
)

# 2. Khởi tạo dịch vụ điều phối
auth_sdk_service = AuthService(
    client=client,
    licenses=licenses_repo,
    audits=auth_audit_repo
)
