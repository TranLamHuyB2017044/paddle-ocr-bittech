from datetime import datetime
from src.database.base_repository import BaseRepository
from bson import ObjectId

class DocumentsRepository(BaseRepository):
    def __init__(self):
        super().__init__("documents")
    
    def save_document(self, user_id, doc_type, sheet_info=None, source_file=None):
        """
        Save document metadata
        
        Args:
            user_id: ID of the user
            doc_type: Type of document
            sheet_info: Dict containing sheet_id, sheet_url, sheet_name
            source_file: Dict containing file_name, file_url
        """
        data = {
            "user_id": ObjectId(user_id) if user_id else None,
            "document_type": doc_type,
            "sheet": sheet_info or {},
            "source_file": source_file or {},
            "created_at": datetime.now()
        }
        return self.create(data)

# Global instance
documents_repo = DocumentsRepository()
