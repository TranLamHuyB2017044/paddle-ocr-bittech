"""
Shared Extractors Alias Package
Forwards legacy imports to src.modules.ocr.extractors
"""
from src.modules.ocr.extractors.openai_extractor import openai_extractor
from src.modules.ocr.extractors.gemini_extractor import gemini_extractor
from src.modules.ocr.extractors.front_extractor import extract_front
from src.modules.ocr.extractors.back_extractor import extract_back

__all__ = ["openai_extractor", "gemini_extractor", "extract_front", "extract_back"]
