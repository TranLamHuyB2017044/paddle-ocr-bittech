"""
Auth Repositories Package
"""
from src.modules.auth.repositories.users_repository import UsersRepository, users_repo
from src.modules.auth.repositories.accounts_repository import AccountRepository, accounts_repo
from src.modules.auth.repositories.auth_repository import AuthRepository, auth_repo
from src.modules.auth.repositories.auth_audit_repository import MongoAuditRepository, auth_audit_repo
from src.modules.auth.repositories.auth_service_repository import AuthServiceRepository, auth_service_repo
from src.modules.auth.repositories.licenses_repository import MongoLicenseRepository, licenses_repo
from src.modules.auth.repositories.audit_log_repository import AuditLogRepository, audit_log_repo, AuditEvent
from src.modules.auth.repositories.workspaces_repository import WorkspacesRepository, workspaces_repo

__all__ = [
    "UsersRepository",
    "users_repo",
    "AccountRepository",
    "accounts_repo",
    "AuthRepository",
    "auth_repo",
    "MongoAuditRepository",
    "auth_audit_repo",
    "AuthServiceRepository",
    "auth_service_repo",
    "MongoLicenseRepository",
    "licenses_repo",
    "AuditLogRepository",
    "audit_log_repo",
    "AuditEvent",
    "WorkspacesRepository",
    "workspaces_repo",
]
