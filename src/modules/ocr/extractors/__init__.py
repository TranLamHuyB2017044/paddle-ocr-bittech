"""
OCR Card Extractors Package
Front and Back ID Card (CCCD/CMND) extraction logic.
"""
from src.modules.ocr.extractors.front_extractor import extract_front
from src.modules.ocr.extractors.back_extractor import extract_back

__all__ = ["extract_front", "extract_back"]
