from datetime import datetime, timezone
from typing import Any, Optional
from bson import ObjectId
from src.core.database.base_repository import BaseRepository

class AuditLogRepository(BaseRepository):
    def __init__(self):
        super().__init__("audit_logs")
        self._ensure_indexes()

    def _ensure_indexes(self):
        try:
            self.collection.create_index([("workspace_id", 1), ("created_at", -1)])
            self.collection.create_index([("action", 1)])
        except Exception as e:
            pass

    def log(
        self,
        action: str,
        actor_user_id: Optional[str] = None,
        account_id: Optional[str] = None,
        workspace_id: Optional[str] = None,
        target_type: str = "category",
        target_id: Optional[str] = None,
        snapshot: Optional[dict] = None,
        affected: Optional[dict] = None,
        reason: Optional[str] = None,
        ip: Optional[str] = None,
        user_agent: Optional[str] = None,
        **extra
    ) -> str:
        """
        Record an audit log entry.
        """
        data: dict[str, Any] = {
            "action": action,
            "actor_user_id": str(actor_user_id) if actor_user_id else None,
            "account_id": str(account_id) if account_id else None,
            "workspace_id": str(workspace_id) if workspace_id else None,
            "target_type": target_type,
            "target_id": str(target_id) if target_id else None,
            "snapshot": snapshot or {},
            "affected": affected or {},
            "reason": reason,
            "ip": ip,
            "user_agent": user_agent,
            "created_at": datetime.now(timezone.utc)
        }
        data.update(extra)
        return str(self.create(data))

    def get_logs_by_workspace(self, workspace_id: str, action: Optional[str] = None, page: int = 1, limit: int = 20):
        query: dict[str, Any] = {"workspace_id": str(workspace_id)}
        if action:
            query["action"] = action

        skip = (page - 1) * limit
        cursor = self.collection.find(query).sort("created_at", -1).skip(skip).limit(limit)
        items = list(cursor)
        for item in items:
            item["_id"] = str(item["_id"])
            if isinstance(item.get("created_at"), datetime):
                item["created_at"] = item["created_at"].isoformat()

        total = self.collection.count_documents(query)
        return items, total

audit_log_repo = AuditLogRepository()
