"""
AuditLogRepository
Ghi lại mọi access event quan trọng liên quan đến file:
- Admin break-glass: xem file của user khác (bắt buộc có reason).
- Unauthorized access attempt.

Schema một record:
{
    "event_type":    str  – "admin_break_glass" | "access_denied" | "file_viewed",
    "actor_user_id": str  – người thực hiện hành động,
    "actor_role":    int  – role tại thời điểm đó,
    "target_doc_id": str  – document liên quan,
    "target_file":   str  – filename / public_id,
    "reason":        str | None – lý do (bắt buộc với break-glass),
    "ip_address":    str,
    "user_agent":    str,
    "timestamp":     datetime,
    "metadata":      dict – thông tin bổ sung,
}
"""
from datetime import datetime
from src.core.database.base_repository import BaseRepository
from src.shared.utils.logger import Log


class AuditLogRepository(BaseRepository):
    def __init__(self):
        super().__init__("audit_logs")
        self.collection.create_index("actor_user_id")
        self.collection.create_index("target_doc_id")
        self.collection.create_index("timestamp")
        self.collection.create_index("event_type")

    def log_event(
        self,
        event_type: str,
        actor_user_id: str,
        actor_role: int,
        target_doc_id: str | None = None,
        target_file: str | None = None,
        reason: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        metadata: dict | None = None,
    ) -> str:
        """
        Ghi một audit event.

        Args:
            event_type: Loại event. Xem hằng số AuditEvent bên dưới.
            reason:     Bắt buộc với 'admin_break_glass', None với các event khác.

        Returns:
            str: _id của log record vừa tạo.
        """
        data = {
            "event_type": event_type,
            "actor_user_id": actor_user_id,
            "actor_role": actor_role,
            "target_doc_id": str(target_doc_id) if target_doc_id else None,
            "target_file": target_file,
            "reason": reason,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "timestamp": datetime.now(),
            "metadata": metadata or {},
        }
        record_id = self.create(data)
        Log.info(
            f"[AuditLog] 📋 [{event_type}] actor={actor_user_id} "
            f"doc={target_doc_id} reason={reason!r}"
        )
        return record_id

    def find_by_document(self, doc_id: str, limit: int = 50) -> list:
        """Lấy audit log theo document, mới nhất trước."""
        return list(
            self.collection.find({"target_doc_id": doc_id})
            .sort("timestamp", -1)
            .limit(limit)
        )

    def find_by_actor(self, actor_user_id: str, limit: int = 100) -> list:
        """Lấy audit log theo người thực hiện."""
        return list(
            self.collection.find({"actor_user_id": actor_user_id})
            .sort("timestamp", -1)
            .limit(limit)
        )


class AuditEvent:
    """Hằng số event type để tránh magic string."""
    FILE_VIEWED         = "file_viewed"
    ADMIN_BREAK_GLASS   = "admin_break_glass"
    ACCESS_DENIED       = "access_denied"
    FILE_DELETED        = "file_deleted"
    SIGNED_URL_ISSUED   = "signed_url_issued"


audit_log_repo = AuditLogRepository()
