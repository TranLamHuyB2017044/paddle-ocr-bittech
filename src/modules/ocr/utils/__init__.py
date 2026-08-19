"""
OCR Utilities Package
Provides OCR processing, spatial extraction, config rules, and post cleaners.
"""
from src.modules.ocr.utils.ocr_utils import (
    ocr_extract,
    preprocess_for_ocr,
    ocr_structure_extract,
    smart_menu_ocr_extract,
    filter_useless_lines,
)
from src.modules.ocr.utils.post_cleaner import PostCleaner
from src.modules.ocr.utils.smart_config import get_smart_config
from src.modules.ocr.utils.smart_spatial_extractor import SmartSpatialExtractor
from src.modules.ocr.utils.text_cleaner import clean_text_lines, clean_text_basic

__all__ = [
    "ocr_extract",
    "preprocess_for_ocr",
    "ocr_structure_extract",
    "smart_menu_ocr_extract",
    "filter_useless_lines",
    "PostCleaner",
    "get_smart_config",
    "SmartSpatialExtractor",
    "clean_text_lines",
    "clean_text_basic",
]
