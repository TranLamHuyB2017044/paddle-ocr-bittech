"""
OCR Repositories Package
"""
from src.modules.ocr.repositories.documents_repository import DocumentsRepository, documents_repo
from src.modules.ocr.repositories.extraction_logs_repository import ExtractionLogsRepository, extraction_logs_repo
from src.modules.ocr.repositories.extraction_reports_repository import ExtractionReportsRepository, extraction_reports_repo
from src.modules.ocr.repositories.corrections_repository import CorrectionsRepository, corrections_repo
from src.modules.ocr.repositories.file_storage_repository import FileStorageRepository, file_storage_repo

__all__ = [
    "DocumentsRepository",
    "documents_repo",
    "ExtractionLogsRepository",
    "extraction_logs_repo",
    "ExtractionReportsRepository",
    "extraction_reports_repo",
    "CorrectionsRepository",
    "corrections_repo",
    "FileStorageRepository",
    "file_storage_repo",
]
