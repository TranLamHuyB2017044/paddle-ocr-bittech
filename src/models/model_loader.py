"""
Model Loader
Load và quản lý OCR và AI models
"""
import os
from paddleocr import PaddleOCR, PPStructureV3
from ..config import OCR_CONFIG
from ..utils.logger import Log
import traceback

class ModelLoader:
    """Singleton class để load và cache models"""
    
    _instance = None
    _ocr = None
    _structure = None
    _device = None
    _rembg_session = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ModelLoader, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize ModelLoader and pre-load only the essential OCR model."""
        # Pre-load only OCR at startup (Minimize RAM)
        self._load_ocr()
        self._load_structure() 
        # self._load_rembg()    # Tạm thời bỏ load

    def _load_ocr(self):
        """Load OCR model only when needed"""
        if self._ocr is None:
            Log.info("📖 Loading PaddleOCR (V5)...")
            try:
                self._ocr = PaddleOCR(**OCR_CONFIG)
                Log.info("✅ PaddleOCR loaded success!")
            except Exception as e:
                Log.error(f"❌ Failed to load PaddleOCR: {e}")
        return self._ocr

    def _load_structure(self):
        """Load Structure model only when needed"""
        if self._structure is None:
            from ..config import STRUCTURE_CONFIG
            Log.info("📖 Loading PP-Structure V3 (Sync mode)...")
            try:
                self._structure = PPStructureV3(**STRUCTURE_CONFIG)
                Log.info("✅ PP-Structure V3 loaded success!")
            except Exception as e:
                Log.error(f"❌ Failed to load PP-Structure: {e}")
        return self._structure

    def _load_rembg(self):
        """Load Rembg model only when needed"""
        if self._rembg_session is None:
            Log.info("🎨 Loading Rembg Model (modnet)...")
            try:
                from rembg import new_session
                self._rembg_session = new_session("modnet")
                Log.info("✅ Rembg Model (modnet) loaded success!")
            except Exception as e:
                Log.error(f"❌ Failed to load Rembg Model: {e}")
        return self._rembg_session

    @property
    def ocr(self):
        """Get OCR instance, loading it ONLY if necessary"""
        if self._ocr is None:
            self._load_ocr()
        return self._ocr

    @property
    def structure(self):
        """Get Structure instance (DISABLED)"""
        if self._structure is None:
            self._load_structure()
        return self._structure

    @property
    def device(self):
        """Get device, default to cpu"""
        if self._device is None:
            self._device = "cpu"
        return self._device

    @property
    def rembg_session(self):
        """Get rembg session (DISABLED)"""
        if self._rembg_session is None:
            # self._load_rembg()
            pass
        return self._rembg_session


# Global instance
model_loader = ModelLoader()
