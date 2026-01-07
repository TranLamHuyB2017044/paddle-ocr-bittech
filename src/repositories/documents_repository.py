from datetime import datetime
from src.database.base_repository import BaseRepository
from bson import ObjectId

class DocumentsRepository(BaseRepository):
    def __init__(self):
        super().__init__("documents")
    
    def save_document(self, user_id, doc_type=None, workspace_id=None, filename=None, status=None, **kwargs):
        """
        Save document metadata (Compatible with both OCR logs and RAG system)
        """
        data = {
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
        
        # Add any other kwargs (sheet_info, source_file, etc.)
        data.update(kwargs)
        
        return str(self.create(data))

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

# Global instance
documents_repo = DocumentsRepository()
