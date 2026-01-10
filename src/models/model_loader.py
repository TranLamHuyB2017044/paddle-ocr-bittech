"""
Model Loader
Load và quản lý OCR và AI models
"""
import os
from paddleocr import PaddleOCR
import torch
from ultralytics import YOLO
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from src.config import MODEL_PATH, OCR_CONFIG, YOLO_MODEL_PATH
from src.utils.logger import Log


class ModelLoader:
    """Singleton class để load và cache models"""
    
    _instance = None
    _ocr = None
    _yolo = None
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
        
        # Load OCR
        Log.info("📖 Loading PaddleOCR...")
        self._ocr = PaddleOCR(**OCR_CONFIG)
        
        # Load YOLO
        if os.path.exists(YOLO_MODEL_PATH):
            Log.info(f"🎯 Loading YOLO model from {YOLO_MODEL_PATH}...")
            self._yolo = YOLO(YOLO_MODEL_PATH)
        else:
            Log.warning(f"⚠️ YOLO model not found at {YOLO_MODEL_PATH}. Layout detection will be skipped.")

        # Setup device
        self._device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        Log.info(f"🖥️  Device: {self._device}")
        
        # Load tokenizer và model
        Log.info(f"🤖 Loading AI model from {MODEL_PATH}...")
        self._tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
        self._model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_PATH).to(self._device)
        self._model.eval()
        
        Log.info("✅ Tất cả models đã được load thành công!")
    
    @property
    def ocr(self):
        """Get OCR instance, loading it if necessary"""
        if self._ocr is None:
            self._load_models()
        return self._ocr
    
    @property
    def yolo(self):
        """Get YOLO instance, loading it if necessary"""
        if self._yolo is None:
            self._load_models()
        return self._yolo

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
