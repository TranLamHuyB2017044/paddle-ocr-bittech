from datetime import datetime
from typing import Any
from src.core.database.base_repository import BaseRepository
from bson import ObjectId

class DocumentsRepository(BaseRepository):
    def __init__(self):
        super().__init__("documents")
    
    def save_document(self, user_id, doc_type=None, workspace_id=None, filename=None,
                      status=None, source_files: list | None = None,
                      raw_text: str | None = None, category: str | None = None, **kwargs):
        """
        Save document metadata (Compatible with both OCR logs and RAG system).
        """
        data: dict[str, Any] = {
            "user_id": ObjectId(user_id) if user_id else None,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
            "is_deleted": False,
            "deleted_at": None,
            "deleted_by": None,
            "deleted_reason": None
        }
        
        # RAG specific fields
        if workspace_id: data["workspace_id"] = str(workspace_id)
        if filename: data["filename"] = filename
        if status: data["status"] = status
        if category: data["category"] = category
        
        # OCR log specific fields (backward compatibility)
        if doc_type: data["document_type"] = doc_type

        # File ownership metadata
        if source_files:
            data["source_files"] = source_files

        # Raw text content (used by upload-text and reindex)
        if raw_text is not None:
            data["raw_text"] = raw_text
        
        # Add any other kwargs (sheet_info, source_file, etc.)
        data.update(kwargs)
        
        return str(self.create(data))

    def find_by_storage_path(self, storage_path: str):
        """
        Tìm document đầu tiên chứa file tại storage_path.
        Dùng để ownership check trên route /uploads/<filename>.
        """
        return self.collection.find_one(
            {"source_files.storage_path": storage_path, "is_deleted": {"$ne": True}}
        )

    def update_status(self, doc_id, status, **kwargs):
        """
        Update document status and metadata
        """
        update_data = {
            "status": status,
            "updated_at": datetime.now()
        }
        update_data.update(kwargs)
        self.collection.update_one(
            {"_id": ObjectId(doc_id)},
            {"$set": update_data}
        )

    def find_by_workspace(self, workspace_id, category: str | None = None, include_deleted: bool = False):
        query: dict[str, Any] = {"workspace_id": str(workspace_id)}
        if not include_deleted:
            query["is_deleted"] = {"$ne": True}
        if category:
            query["category"] = category
        return self.find_all(query)

    def count_by_workspace(self, workspace_id, category: str | None = None) -> int:
        query: dict[str, Any] = {
            "workspace_id": str(workspace_id),
            "is_deleted": {"$ne": True}
        }
        if category:
            query["category"] = category
        return self.collection.count_documents(query)

    def soft_delete_by_category(self, workspace_id: str, category_slug: str, deleted_by: str | None = None) -> list:
        """
        Soft-delete all documents belonging to a category.
        Returns the list of affected document dicts (including id and filename).
        """
        from datetime import timezone
        now = datetime.now(timezone.utc)
        query = {
            "workspace_id": str(workspace_id),
            "category": category_slug,
            "is_deleted": {"$ne": True}
        }
        docs = list(self.collection.find(query, {"_id": 1, "filename": 1, "category": 1, "raw_text": 1}))
        if docs:
            self.collection.update_many(
                query,
                {"$set": {
                    "is_deleted": True,
                    "deleted_at": now,
                    "deleted_by": str(deleted_by) if deleted_by else None,
                    "deleted_reason": f"category_deleted:{category_slug}",
                    "updated_at": datetime.now()
                }}
            )
        return docs

    def restore_by_category(self, workspace_id: str, category_slug: str) -> list:
        """
        Restore documents that were soft-deleted because of this category deletion.
        """
        query = {
            "workspace_id": str(workspace_id),
            "category": category_slug,
            "is_deleted": True,
            "deleted_reason": f"category_deleted:{category_slug}"
        }
        docs = list(self.collection.find(query))
        if docs:
            self.collection.update_many(
                query,
                {"$set": {
                    "is_deleted": False,
                    "deleted_at": None,
                    "deleted_by": None,
                    "deleted_reason": None,
                    "updated_at": datetime.now()
                }}
            )
        return docs

    def delete_by_user(self, user_id):
        uid = ObjectId(user_id) if isinstance(user_id, str) else user_id
        result = self.collection.delete_many({"user_id": uid})
        return result.deleted_count

    def delete_document(self, doc_id: str) -> bool:
        """
        Xóa một document record khỏi MongoDB theo ID.
        """
        result = self.collection.delete_one({"_id": ObjectId(doc_id)})
        return result.deleted_count > 0

    def update_metadata(self, doc_id: str, **fields) -> bool:
        if not fields:
            return False
        fields["updated_at"] = datetime.now()
        result = self.collection.update_one(
            {"_id": ObjectId(doc_id)},
            {"$set": fields}
        )
        return result.matched_count > 0

    def update_raw_text(self, doc_id: str, raw_text: str) -> bool:
        result = self.collection.update_one(
            {"_id": ObjectId(doc_id)},
            {"$set": {"raw_text": raw_text, "updated_at": datetime.now()}}
        )
        return result.matched_count > 0

# Global instance
documents_repo = DocumentsRepository()
