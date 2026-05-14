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

    def get_recent_extractions(self, user_ids, limit=5):
        """
        Get recent extractions for a user or list of users.
        Combines total time and provider from metadata to display on mini card.
        """
        from src.repositories.users_repository import users_repo
        from src.repositories.documents_repository import documents_repo
        
        try:
            # None = admin, lấy toàn bộ hệ thống
            if user_ids is None:
                cursor = self.collection.find({}).sort("created_at", -1).limit(limit)
            else:
                if not isinstance(user_ids, list):
                    uid = ObjectId(user_ids) if isinstance(user_ids, str) else user_ids
                    uids = [uid]
                else:
                    uids = [ObjectId(u) if isinstance(u, str) else u for u in user_ids]
                cursor = self.collection.find({"user_id": {"$in": uids}}).sort("created_at", -1).limit(limit)
            
            recent_logs = []
            
            # Simple cache for mapping user_id to fullname
            user_cache = {}
            # Simple cache for mapping document_id to filename
            doc_cache = {}

            for doc in cursor:
                # Get detector account info
                doc_uid = doc.get("user_id")
                detector_name = "Unknown"
                if doc_uid:
                    uid_str = str(doc_uid)
                    if uid_str not in user_cache:
                        user_info = users_repo.find_by_id(doc_uid)
                        user_cache[uid_str] = user_info.get("fullname", "Unknown") if user_info else "Unknown"
                    detector_name = user_cache[uid_str]

                # Get filename from documents collection
                filename = None
                raw_doc_id = doc.get("document_id")
                if raw_doc_id:
                    doc_id_str = str(raw_doc_id)
                    if doc_id_str not in doc_cache:
                        try:
                            document = documents_repo.find_by_id(doc_id_str)
                            doc_cache[doc_id_str] = document.get("filename") if document else None
                        except Exception:
                            doc_cache[doc_id_str] = None
                    filename = doc_cache[doc_id_str]

                # Extract interesting metadata details
                metadata = doc.get("metadata", {}) or {}
                
                # Fetch provider if available (often stored in debug info or metadata)
                provider = "unknown"
                total_time = "N/A"
                if isinstance(metadata, dict):
                    provider = metadata.get("provider", "unknown")
                    total_time = metadata.get("total_time", "N/A")
                
                recent_logs.append({
                    "document_id": str(raw_doc_id),
                    "document_type": doc.get("document_type"),
                    "filename": filename,
                    "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
                    "total_time": total_time,
                    "detector_name": detector_name,
                    "extraction_result": doc.get("extraction_result")
                })
            
            return recent_logs
        except Exception as e:
            print(f"Error getting recent extractions: {e}")
            return []

    def get_paginated_extractions(self, user_id, page=1, limit=10):
        from src.repositories.documents_repository import documents_repo
        from src.repositories.users_repository import users_repo
        
        try:
            uid = ObjectId(user_id) if isinstance(user_id, str) else user_id
            query = {"user_id": uid}
            
            skip = (page - 1) * limit
            cursor = self.collection.find(query).sort("created_at", -1).skip(skip).limit(limit)
            total = self.collection.count_documents(query)
            
            logs = []
            doc_cache = {}
            
            # Simple cache for mapping user_id to fullname
            user_cache = {}

            for doc in cursor:
                # Get detector account info
                doc_uid = doc.get("user_id")
                detector_name = "Unknown"
                if doc_uid:
                    uid_str = str(doc_uid)
                    if uid_str not in user_cache:
                        user_info = users_repo.find_by_id(doc_uid)
                        user_cache[uid_str] = user_info.get("fullname", "Unknown") if user_info else "Unknown"
                    detector_name = user_cache[uid_str]
                    
                filename = None
                raw_doc_id = doc.get("document_id")
                if raw_doc_id:
                    doc_id_str = str(raw_doc_id)
                    if doc_id_str not in doc_cache:
                        try:
                            document = documents_repo.find_by_id(doc_id_str)
                            doc_cache[doc_id_str] = document.get("filename") if document else None
                        except Exception:
                            doc_cache[doc_id_str] = None
                    filename = doc_cache[doc_id_str]

                metadata = doc.get("metadata", {}) or {}
                total_time = "N/A"
                if isinstance(metadata, dict):
                    total_time = metadata.get("total_time", "N/A")
                
                logs.append({
                    "document_id": str(raw_doc_id) if raw_doc_id else None,
                    "document_type": doc.get("document_type"),
                    "filename": filename,
                    "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
                    "total_time": total_time,
                    "detector_name": detector_name,
                    "extraction_result": doc.get("extraction_result")
                })
            
            return {
                "total": total,
                "page": page,
                "limit": limit,
                "data": logs,
                "total_pages": (total + limit - 1) // limit if limit > 0 else 0
            }
        except Exception as e:
            print(f"Error getting paginated extractions: {e}")
            return {"total": 0, "page": page, "limit": limit, "data": [], "total_pages": 0}

# Global instance
extraction_logs_repo = ExtractionLogsRepository()
