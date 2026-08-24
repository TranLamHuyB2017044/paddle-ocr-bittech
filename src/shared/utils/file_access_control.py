"""
File Access Control (RBAC Engine)
Kiểm tra quyền xem file theo policy:

  role=2 (User/Owner): chỉ xem file của mình.
  role=1 (Manager):    xem được file trong cùng account_id (cùng công ty/workspace).
  role=0 (Admin):      chỉ xem qua cơ chế break-glass — bắt buộc cung cấp reason,
                       mọi lần xem đều bị ghi audit log.
"""
from flask import request
from src.shared.utils.logger import Log


# ── Constants ─────────────────────────────────────────────────────────────────
ROLE_ADMIN   = 0
ROLE_MANAGER = 1
ROLE_USER    = 2


class FileAccessResult:
    """Kết quả kiểm tra quyền truy cập."""

    def __init__(self, allowed: bool, reason: str = "", require_audit: bool = False):
        self.allowed       = allowed
        self.reason        = reason        # Thông điệp trả về client nếu bị từ chối
        self.require_audit = require_audit # True khi đây là break-glass (admin)

    def __bool__(self):
        return self.allowed

    @classmethod
    def ok(cls, require_audit: bool = False):
        return cls(allowed=True, require_audit=require_audit)

    @classmethod
    def denied(cls, reason: str):
        return cls(allowed=False, reason=reason)


def check_file_access(
    g_user: dict,
    doc: dict,
    break_glass_reason: str | None = None,
) -> FileAccessResult:
    """
    Kiểm tra xem g_user có quyền xem file thuộc doc hay không.

    Args:
        g_user:              Flask g.user dict (phải có 'role', '_id', 'account_id').
        doc:                 Document record từ MongoDB (phải có 'user_id', 'account_id').
        break_glass_reason:  Lý do admin cung cấp khi muốn xem file người khác.
                             Nếu None và actor là admin → từ chối, yêu cầu cung cấp reason.

    Returns:
        FileAccessResult
    """
    actor_role       = g_user.get("role", ROLE_USER)
    actor_user_id    = str(g_user.get("_id", ""))
    actor_account_id = str(g_user.get("account_id", "")) if g_user.get("account_id") else ""

    doc_owner_id     = str(doc.get("user_id", ""))
    doc_account_id   = str(doc.get("account_id", "")) if doc.get("account_id") else ""

    # ── Role 2: User (Owner only) ──────────────────────────────────────────────
    if actor_role == ROLE_USER:
        if actor_user_id == doc_owner_id:
            return FileAccessResult.ok()
        return FileAccessResult.denied(
            "Bạn không có quyền truy cập file này."
        )

    # ── Role 1: Manager (same account) ────────────────────────────────────────
    if actor_role == ROLE_MANAGER:
        if actor_user_id == doc_owner_id:
            return FileAccessResult.ok()
        # Cùng account_id → manager được xem
        if actor_account_id and doc_account_id and actor_account_id == doc_account_id:
            Log.info(
                f"[RBAC] Manager {actor_user_id} accessing file of user {doc_owner_id} "
                f"within account {actor_account_id}"
            )
            return FileAccessResult.ok()
        return FileAccessResult.denied(
            "Manager chỉ được xem file của thành viên trong cùng tổ chức."
        )

    # ── Role 0: Admin (break-glass) ───────────────────────────────────────────
    if actor_role == ROLE_ADMIN:
        # Owner case — không cần break-glass
        if actor_user_id == doc_owner_id:
            return FileAccessResult.ok()

        # Break-glass: bắt buộc có reason
        if not break_glass_reason or not break_glass_reason.strip():
            return FileAccessResult.denied(
                "Admin phải cung cấp lý do (break_glass_reason) để xem file của người dùng khác."
            )

        Log.warning(
            f"[RBAC] 🔓 Admin BREAK-GLASS: actor={actor_user_id} "
            f"doc_owner={doc_owner_id} reason={break_glass_reason!r}"
        )
        # Trả về ok nhưng đánh dấu require_audit để caller ghi log
        return FileAccessResult(allowed=True, require_audit=True)

    # Fallback
    return FileAccessResult.denied("Vai trò không xác định.")


def get_request_context() -> dict:
    """Lấy IP và User-Agent từ request hiện tại (nếu có)."""
    try:
        return {
            "ip_address": request.remote_addr,
            "user_agent": request.headers.get("User-Agent", ""),
        }
    except RuntimeError:
        return {"ip_address": None, "user_agent": None}
