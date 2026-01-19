from src.repositories.extraction_logs_repository import extraction_logs_repo
from src.repositories.documents_repository import documents_repo
import os

class LogService:
    def save_logs(self, user_id, doc_type, file_paths, extraction_data=None, metadata=None):
        """
        Save extraction logs and document metadata to MongoDB.
        
        Args:
            user_id: ID of the user
            doc_type: Type of document
            file_paths: List of temporary file paths used in detection
            extraction_data: Dictionary containing extracted data (optional info for sheet)
            metadata: Usage metadata (token counts)
        """
        if not user_id:
            # We can log anonymously or skip if strict.
            # User schema implies user_id is ObjectId, so usually required.
            # But let's proceed if null, just logging with None.
            pass

        saved_file_url = None
        saved_file_name = None
        
        # Save source file (first one)
        # User requested NOT to save the physical file locally (no copy to storage).
        # But wants to save "url" to document collection.
        # Since we are not persisting the file, we can only log the original filename 
        # and perhaps the relative path of where it was uploaded (even if deleted later).
        if file_paths and len(file_paths) > 0:
            first_path = file_paths[0]
            if first_path.startswith("http"):
                saved_file_url = first_path
                saved_file_name = os.path.basename(first_path)
            else:
                saved_file_name = os.path.basename(first_path)
                # We map the URL to the uploads folder structure, though it might be cleaned up.
                saved_file_url = f"/uploads/{saved_file_name}"
        
        # Determine Sheet Info
        # Check if extraction_data has sheet info. 
        # Usually it doesn't unless we injected it.
        # But we look for it just in case.
        data_sheet = extraction_data.get("sheet_info", {}) if extraction_data else {}
        
        sheet_info = {
            "sheet_id": data_sheet.get("sheet_id"),
            "sheet_url": data_sheet.get("sheet_url"),
            "sheet_name": data_sheet.get("sheet_name")
        }
        
        # Save Document
        # We perform this even if user_id is None? Yes.
        document_id = documents_repo.save_document(
            user_id=user_id,
            doc_type=doc_type,
            sheet_info=sheet_info,
            source_file={
                "file_name": saved_file_name,
                "file_url": saved_file_url
            } if saved_file_url else None
        )
        
        # Save Extraction Log
        extraction_logs_repo.log_extraction(
            user_id=user_id,
            doc_type=doc_type,
            saved_to_sheet=bool(sheet_info.get("sheet_id")),
            sheet_id=sheet_info.get("sheet_id"),
            metadata=metadata
        )

        return document_id

log_service = LogService()
