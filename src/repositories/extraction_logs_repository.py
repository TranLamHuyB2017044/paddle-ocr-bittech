from datetime import datetime
from src.database.base_repository import BaseRepository
from bson import ObjectId

class ExtractionLogsRepository(BaseRepository):
    def __init__(self):
        super().__init__("extraction_logs")
    
    def log_extraction(self, user_id, doc_type, saved_to_sheet=False, sheet_id=None, metadata=None):
        """
        Create a new extraction log
        """
        data = {
            "user_id": ObjectId(user_id) if user_id else None,
            "document_type": doc_type,
            "saved_to_sheet": saved_to_sheet,
            "sheet_id": sheet_id,
            "metadata": metadata,
            "created_at": datetime.now()
        }
        return self.create(data)

    def count_today_by_user(self, user_id):
        """
        Count number of extractions for a user today
        """
        if not user_id:
            return 0
            
        now = datetime.now()
        start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
        
        query = {
            "user_id": ObjectId(user_id),
            "created_at": {"$gte": start_of_day}
        }
        
        return self.collection.count_documents(query)

    def delete_by_user(self, user_id):
        uid = ObjectId(user_id) if isinstance(user_id, str) else user_id
        result = self.collection.delete_many({"user_id": uid})
        return result.deleted_count

# Global instance
extraction_logs_repo = ExtractionLogsRepository()
