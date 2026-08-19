"""
Auth Services Package
Provides user authentication, OAuth flow, token management, and Bittech SDK services.
"""
from src.modules.auth.services.auth_service import AuthService, auth_service
from src.modules.auth.services.auth_sdk_service import auth_sdk_service
from src.modules.auth.services.oauth_service import OAuthService, oauth_service, DRIVE_SCOPES, SCOPES
from src.modules.auth.services.token_service import TokenService, token_service
from src.modules.auth.services.multi_connect_service import (
    call_client_register_post,
    call_system_connections_get,
    call_revoke_api_key,
    call_auth_token,
    upload_document,
)

__all__ = [
    "AuthService",
    "auth_service",
    "auth_sdk_service",
    "OAuthService",
    "oauth_service",
    "DRIVE_SCOPES",
    "SCOPES",
    "TokenService",
    "token_service",
    "call_client_register_post",
    "call_system_connections_get",
    "call_revoke_api_key",
    "call_auth_token",
    "upload_document",
]
