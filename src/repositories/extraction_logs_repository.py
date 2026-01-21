from datetime import datetime
from src.database.base_repository import BaseRepository
from bson import ObjectId

class ExtractionLogsRepository(BaseRepository):
    def __init__(self):
        super().__init__("extraction_logs")
    
    def log_extraction(self, user_id, doc_type, saved_to_sheet=False, sheet_id=None, metadata=None, extraction_result=None, document_id=None):
        """
        Create a new extraction log
        """
        doc_oid = None
        if document_id:
             try:
                 doc_oid = ObjectId(document_id)
             except:
                 doc_oid = str(document_id) # Store as string if not valid ObjectId

        data = {
            "user_id": ObjectId(user_id) if user_id else None,
            "document_id": doc_oid,
            "document_type": doc_type,
            "saved_to_sheet": saved_to_sheet,
            "sheet_id": sheet_id,
            "metadata": metadata,
            "extraction_result": extraction_result, # Store result for reporting/accuracy check
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

    def update_report(self, document_id, reason, details=None, extraction_result=None):
        """
        Update report information for an extraction log.
        Optionally update extraction_result if client sends it (e.g. for logs created before this field was added)
        """
        try:
            print(f"[Repo-Log] Updating report for doc: {document_id}, Reason: {reason}")
            
            update_data = {
                "report_info": {
                    "reason": reason,
                    "details": details, # Optional text from user (correction or comment)
                    "reported_at": datetime.now()
                }
            }
            
            # If client provides the extraction result (e.g. they want to snapshot what they saw), save it
            if extraction_result:
                update_data["extraction_result"] = extraction_result
            
            # Attempt 1: Find by ObjectId
            try:
                doc_oid = ObjectId(document_id)
                result = self.collection.update_one(
                    {"document_id": doc_oid}, 
                    {"$set": update_data}
                )
                if result.matched_count > 0:
                     print(f"[Repo-Log] Report updated via ObjectId: {doc_oid}")
                     return True
            except:
                pass # Not a valid objectId

            # Attempt 2: Find by String (if ObjectId failed or matched nothing)
            # Some old records or manually inserted ones might have string ID
            result = self.collection.update_one(
                {"document_id": str(document_id)}, 
                {"$set": update_data}
            )
            
            if result.matched_count > 0:
                print(f"[Repo-Log] Report updated via String: {document_id}")
                return True
                
            print(f"[Repo-Log] ⚠️ Log NOT found for doc_id: {document_id}")
            return False
            
        except Exception as e:
            print(f"Update report error: {e}")
            return False

# Global instance
extraction_logs_repo = ExtractionLogsRepository()
