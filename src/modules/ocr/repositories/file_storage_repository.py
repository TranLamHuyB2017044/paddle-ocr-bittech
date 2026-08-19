"""
FileStorageRepository
Quản lý metadata của file ảnh gốc được lưu trên Cloudinary (private/authenticated).

Schema một record:
{
    "document_id":        str   – ObjectId của document liên kết,
    "owner_user_id":      str   – ObjectId của user sở hữu,
    "account_id":         str   – account/công ty (để manager check),
    "workspace_id":       str   – workspace liên kết (nếu có),
    "cloudinary_public_id": str,
    "resource_type":      str   – "image" | "raw",
    "storage_provider":   str   – "cloudinary",
    "original_filename":  str,
    "expires_at":         datetime – thời điểm retention tự xóa,
    "created_at":         datetime,
    "deleted_at":         datetime | None – đánh dấu soft-delete sau khi xóa cloud,
}
"""
from datetime import datetime, timedelta
from bson import ObjectId
from src.core.database.base_repository import BaseRepository
from src.shared.utils.logger import Log

# Thời gian giữ ảnh mặc định (ngày). Override bằng biến môi trường hoặc workspace setting.
DEFAULT_RETENTION_DAYS = 7


class FileStorageRepository(BaseRepository):
    def __init__(self):
        super().__init__("file_storage")
        # Index để query nhanh theo document & retention job
        self.collection.create_index("document_id")
        self.collection.create_index("owner_user_id")
        self.collection.create_index("account_id")
        self.collection.create_index("expires_at")

    def save_file_metadata(
        self,
        document_id: str,
        owner_user_id: str,
        cloudinary_public_id: str,
        original_filename: str,
        resource_type: str = "image",
        account_id: str | None = None,
        workspace_id: str | None = None,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> str:
        """
        Lưu metadata của file ảnh vừa upload lên Cloudinary.

        Returns:
            str: _id của record vừa tạo.
        """
        expires_at = datetime.now() + timedelta(days=retention_days)
        data = {
            "document_id": document_id,
            "owner_user_id": owner_user_id,
            "account_id": account_id,
            "workspace_id": workspace_id,
            "cloudinary_public_id": cloudinary_public_id,
            "resource_type": resource_type,
            "storage_provider": "cloudinary",
            "original_filename": original_filename,
            "expires_at": expires_at,
            "created_at": datetime.now(),
            "deleted_at": None,
        }
        record_id = self.create(data)
        Log.info(f"[FileStorage] 💾 Saved metadata for '{original_filename}' → expires {expires_at.date()}")
        return record_id

    def find_by_document(self, document_id: str) -> list:
        """Trả về tất cả file metadata thuộc về một document."""
        return list(self.collection.find({"document_id": document_id, "deleted_at": None}))

    def find_by_document_and_owner(self, document_id: str, owner_user_id: str) -> list:
        """Lấy file còn hiệu lực của một document/session thuộc đúng owner."""
        return list(self.collection.find({
            "document_id": document_id,
            "owner_user_id": str(owner_user_id),
            "deleted_at": None,
        }))

    def find_expired(self) -> list:
        """
        Trả về tất cả record đã quá hạn nhưng chưa bị xóa.
        Dùng cho retention job.
        """
        return list(self.collection.find({
            "expires_at": {"$lt": datetime.now()},
            "deleted_at": None
        }))

    def mark_deleted(self, record_id: str):
        """Soft-delete: đánh dấu deleted_at sau khi xóa khỏi Cloudinary."""
        self.collection.update_one(
            {"_id": ObjectId(record_id)},
            {"$set": {"deleted_at": datetime.now()}}
        )

    def mark_deleted_many(self, record_ids: list[str]) -> int:
        """Soft-delete nhiều record sau khi asset Cloudinary đã được xóa."""
        object_ids = []
        for record_id in record_ids:
            try:
                object_ids.append(ObjectId(record_id))
            except Exception:
                continue
        if not object_ids:
            return 0
        result = self.collection.update_many(
            {"_id": {"$in": object_ids}},
            {"$set": {"deleted_at": datetime.now()}},
        )
        return result.modified_count


file_storage_repo = FileStorageRepository()
