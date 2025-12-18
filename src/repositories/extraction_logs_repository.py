from datetime import datetime
from src.database.base_repository import BaseRepository
from bson import ObjectId

class ExtractionLogsRepository(BaseRepository):
    def __init__(self):
        super().__init__("extraction_logs")
    
    def log_extraction(self, user_id, doc_type, saved_to_sheet=False, sheet_id=None):
        """
        Create a new extraction log
        """
        data = {
            "user_id": ObjectId(user_id) if user_id else None,
            "document_type": doc_type,
            "saved_to_sheet": saved_to_sheet,
            "sheet_id": sheet_id,
            "created_at": datetime.now()
        }
        return self.create(data)

# Global instance
extraction_logs_repo = ExtractionLogsRepository()
