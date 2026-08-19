from datetime import datetime, timezone
from typing import Any, Optional, Union
from src.database.base_repository import BaseRepository

class MongoLicenseRepository(BaseRepository):
    def __init__(self):
        super().__init__("licenses")
        self.collection.create_index("license_key", unique=True)
        self.collection.create_index("status")
        self.collection.create_index("expired_at")
        self.collection.create_index("created_at")

    def find_latest(self) -> Optional[dict[str, Any]]:
        """
        Returns the latest license record from the database.
        """
        record = self.collection.find_one(sort=[("created_at", -1)])
        return record

    def find_active(self, now: datetime) -> Optional[dict[str, Any]]:
        """
        Finds the active license record where status is 1 and not expired.
        """
        # Ensure 'now' is naive or UTC to compare with Mongo dates correctly
        # In PyMongo, datetime fields are retrieved as naive datetimes representing UTC,
        # or we might need to query them. If 'now' is timezone-aware, we convert it to naive UTC.
        if now.tzinfo is not None:
            now_utc = now.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            now_utc = now

        query = {
            "status": 1,
            "$or": [
                {"expired_at": {"$gt": now_utc}},
                {"expired_at": None}
            ]
        }
        return self.collection.find_one(query, sort=[("created_at", -1)])

    def save_pending(
        self,
        *,
        public_id: str,
        license_key: str,
        signature: Optional[str],
        expired_at: Union[datetime, str],
        notes: Optional[str],
        connection_id: int = 12,
    ) -> dict[str, Any]:
        """
        Saves a pending license to the database (status=0).
        """
        if isinstance(expired_at, str):
            clean_str = expired_at.replace("Z", "+00:00")
            expired_at_dt = datetime.fromisoformat(clean_str)
        else:
            expired_at_dt = expired_at

        # Ensure expired_at is stored without timezone info for PyMongo consistency,
        # since PyMongo stores naive datetimes representing UTC.
        if expired_at_dt.tzinfo is not None:
            expired_at_naive = expired_at_dt.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            expired_at_naive = expired_at_dt

        record = {
            "public_id": public_id,
            "license_key": license_key,
            "signature": signature,
            "expired_at": expired_at_naive,
            "status": 0,  # 0 = pending, 1 = active
            "notes": notes,
            "connection_id": connection_id,
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
        
        self.collection.update_one(
            {"license_key": license_key},
            {"$set": record},
            upsert=True
        )
        return record

    def mark_verified(
        self,
        license_key: str,
        verified_at: datetime,
    ) -> None:
        """
        Marks a license as verified and active (status=1).
        """
        if verified_at.tzinfo is not None:
            verified_at_naive = verified_at.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            verified_at_naive = verified_at

        self.collection.update_one(
            {"license_key": license_key},
            {
                "$set": {
                    "status": 1,
                    "verified_at": verified_at_naive,
                    "updated_at": datetime.now()
                }
            }
        )

licenses_repo = MongoLicenseRepository()
