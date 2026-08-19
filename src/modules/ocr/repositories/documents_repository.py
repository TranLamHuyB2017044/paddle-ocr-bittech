from datetime import datetime
from typing import Any
from src.core.database.base_repository import BaseRepository
from bson import ObjectId

class DocumentsRepository(BaseRepository):
    def __init__(self):
        super().__init__("documents")
    
    def save_document(self, user_id, doc_type=None, workspace_id=None, filename=None,
                      status=None, source_files: list | None = None,
                      raw_text: str | None = None, **kwargs):
        """
        Save document metadata (Compatible with both OCR logs and RAG system).

        Args:
            source_files: Danh sách metadata file đã lưu trên disk, mỗi phần tử có dạng:
                {
                    "file_name": "20260514_101010_0_front.jpg",
                    "storage_path": "uploads/20260514_101010_0_front.jpg"
                }
                Dùng để thực hiện ownership check khi user request /uploads/<filename>.
            raw_text: Nội dung văn bản thô (dùng cho RAG upload-text và reindex).
        """
        data: dict[str, Any] = {
            "user_id": ObjectId(user_id) if user_id else None,
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
        
        # RAG specific fields
        if workspace_id: data["workspace_id"] = workspace_id
        if filename: data["filename"] = filename
        if status: data["status"] = status
        
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

        Args:
            storage_path: Đường dẫn tương đối, ví dụ "uploads/20260514_front.jpg"

        Returns:
            Document dict hoặc None nếu không tìm thấy.
        """
        return self.collection.find_one(
            {"source_files.storage_path": storage_path}
        )

    def update_status(self, doc_id, status, **kwargs):
        """
        Update document status and metadata
        """
        update_data = {
            "status": status,
            "updated_at": datetime.now()
        }
        
        # Add any other fields (total_chunks, error_message, result, etc.)
        update_data.update(kwargs)
            
        self.collection.update_one(
            {"_id": ObjectId(doc_id)},
            {"$set": update_data}
        )

    def find_by_workspace(self, workspace_id):
        return self.find_all({"workspace_id": workspace_id})

    def delete_by_user(self, user_id):
        uid = ObjectId(user_id) if isinstance(user_id, str) else user_id
        result = self.collection.delete_many({"user_id": uid})
        return result.deleted_count

    def delete_document(self, doc_id: str) -> bool:
        """
        Xóa một document record khỏi MongoDB theo ID.
        Trả về True nếu xóa thành công, False nếu không tìm thấy.
        """
        result = self.collection.delete_one({"_id": ObjectId(doc_id)})
        return result.deleted_count > 0

    def update_metadata(self, doc_id: str, **fields) -> bool:
        """
        Cập nhật các trường metadata của document (không ảnh hưởng đến Qdrant vectors).
        Các trường được phép cập nhật: filename, description, tags, v.v.
        Trả về True nếu tìm thấy và cập nhật thành công.
        """
        if not fields:
            return False
        fields["updated_at"] = datetime.now()
        result = self.collection.update_one(
            {"_id": ObjectId(doc_id)},
            {"$set": fields}
        )
        return result.matched_count > 0

    def update_raw_text(self, doc_id: str, raw_text: str) -> bool:
        """
        Cập nhật raw_text của document (dùng sau khi reindex hoặc update-text).
        """
        result = self.collection.update_one(
            {"_id": ObjectId(doc_id)},
            {"$set": {"raw_text": raw_text, "updated_at": datetime.now()}}
        )
        return result.matched_count > 0

# Global instance
documents_repo = DocumentsRepository()
