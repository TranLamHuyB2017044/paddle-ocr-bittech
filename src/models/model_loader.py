"""
Model Loader
Load và quản lý OCR và AI models
"""
import os
from paddleocr import PaddleOCR, PPStructureV3
import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from src.config import MODEL_PATH, OCR_CONFIG
from src.utils.logger import Log
import traceback

class ModelLoader:
    """Singleton class để load và cache models"""
    
    _instance = None
    _ocr = None
    _structure = None
    _tokenizer = None
    _model = None
    _device = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ModelLoader, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize ModelLoader instance without loading models immediately"""
        pass
    
    def _load_models(self):
        """Load all required models"""
        Log.info("🔄 Đang load models...")
        
        # 1. Load OCR
        if self._ocr is None:
            Log.info("📖 Loading PaddleOCR (V5)...")
            try:
                self._ocr = PaddleOCR(**OCR_CONFIG)
                Log.info("✅ PaddleOCR loaded success!")
            except Exception as e:
                Log.error(f"❌ Failed to load PaddleOCR: {e}")

        # 1.1 Load Structure OCR
        if self._structure is None:
            from src.config import STRUCTURE_CONFIG
            Log.info("📖 Loading PP-Structure V3 (Sync mode)...")
            try:
                self._structure = PPStructureV3(**STRUCTURE_CONFIG)
                Log.info("✅ PP-Structure V3 loaded success!")
            except Exception as e:
                Log.error(f"❌ Failed to load PP-Structure: {e}")


        # 2. Setup device & AI Models
        if self._device is None:
            self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            Log.info(f"🖥️  Device selected: {self._device}")

        if self._model is None:
            Log.info(f"🤖 Loading AI model from {MODEL_PATH}...")
            try:
                self._tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
                self._model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_PATH).to(self._device)
                self._model.eval()
                Log.info("✅ AI models loaded success!")
            except Exception as e:
                Log.error(f"❌ Failed to load AI models: {e}")
                traceback.print_exc()
    
    @property
    def ocr(self):
        """Get OCR instance, loading it if necessary"""
        if self._ocr is None:
            self._load_models()
        return self._ocr

    @property
    def structure(self):
        """Get Structure instance, loading it if necessary"""
        if self._structure is None:
            self._load_models()
        return self._structure

    
    @property
    def tokenizer(self):
        """Get tokenizer instance, loading it if necessary"""
        if self._tokenizer is None:
            self._load_models()
        return self._tokenizer
    
    @property
    def model(self):
        """Get model instance, loading it if necessary"""
        if self._model is None:
            self._load_models()
        return self._model
    
    @property
    def device(self):
        """Get device, loading it if necessary"""
        if self._device is None:
            self._load_models()
        return self._device


# Global instance
model_loader = ModelLoader()
