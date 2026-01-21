from datetime import datetime
from src.database.base_repository import BaseRepository
from bson import ObjectId

class ExtractionReportsRepository(BaseRepository):
    def __init__(self):
        super().__init__("extraction_reports")
    
    def create_report(self, document_id, user_id, reason, details=None, extraction_result=None, doc_type=None):
        """
        Create a new extraction error report
        
        Args:
            document_id: ID of the document being reported
            user_id: ID of the user who submitted the report
            reason: Reason for the report (e.g., "Sai thông tin tên/ngày sinh")
            details: Optional detailed explanation from user
            extraction_result: The extraction result that was incorrect
            doc_type: Type of document (idCard, driverLicense, etc.)
        
        Returns:
            str: ID of the created report
        """
        doc_oid = None
        if document_id:
            try:
                doc_oid = ObjectId(document_id)
            except:
                doc_oid = str(document_id)
        
        user_oid = None
        if user_id:
            try:
                user_oid = ObjectId(user_id)
            except:
                user_oid = str(user_id)
        
        data = {
            "document_id": doc_oid,
            "user_id": user_oid,
            "doc_type": doc_type,
            "reason": reason,
            "details": details,
            "extraction_result": extraction_result,
            "status": "pending",  # pending, reviewed, resolved
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
        
        report_id = self.create(data)
        return str(report_id)
    
    def find_by_document(self, document_id):
        """
        Find all reports for a specific document
        """
        try:
            doc_oid = ObjectId(document_id)
            return self.find_all({"document_id": doc_oid})
        except:
            return self.find_all({"document_id": str(document_id)})
    
    def find_by_user(self, user_id, limit=50):
        """
        Find all reports submitted by a user
        """
        try:
            user_oid = ObjectId(user_id)
            query = {"user_id": user_oid}
        except:
            query = {"user_id": str(user_id)}
        
        return list(self.collection.find(query).sort("created_at", -1).limit(limit))
    
    def find_pending_reports(self, limit=100):
        """
        Find all pending reports for admin review
        """
        return list(self.collection.find({"status": "pending"}).sort("created_at", -1).limit(limit))
    
    def update_status(self, report_id, status, admin_notes=None):
        """
        Update report status (for admin use)
        
        Args:
            report_id: ID of the report
            status: New status (pending, reviewed, resolved)
            admin_notes: Optional notes from admin
        """
        try:
            update_data = {
                "status": status,
                "updated_at": datetime.now()
            }
            
            if admin_notes:
                update_data["admin_notes"] = admin_notes
            
            result = self.collection.update_one(
                {"_id": ObjectId(report_id)},
                {"$set": update_data}
            )
            
            return result.modified_count > 0
        except Exception as e:
            print(f"[ExtractionReports] Update status error: {e}")
            return False
    
    def count_by_status(self, status="pending"):
        """
        Count reports by status
        """
        return self.collection.count_documents({"status": status})
    
    def count_by_doc_type(self, doc_type):
        """
        Count reports by document type
        """
        return self.collection.count_documents({"doc_type": doc_type})

# Global instance
extraction_reports_repo = ExtractionReportsRepository()
