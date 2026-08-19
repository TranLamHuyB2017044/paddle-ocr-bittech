"""
Model Loader
Load và quản lý DeepDoc + VietOCR + VieNeu-TTS models
"""
import os
import traceback
import numpy as np
import json
import threading
import onnxruntime as ort
from PIL import Image
from src.shared.utils.logger import Log
from vietocr.tool.predictor import Predictor
from vietocr.tool.config import Cfg
from huggingface_hub import hf_hub_download

# [FIX] Sửa lỗi 'PIL.Image' has no attribute 'ANTIALIAS' cho Pillow 10+
if not hasattr(Image, 'ANTIALIAS'):
    setattr(Image, 'ANTIALIAS', Image.Resampling.LANCZOS)

class VietOCRHandwrittenPredictor:
    def __init__(self):
        Log.info("📖 Tải model VietOCR Handwritten từ Hugging Face...")
        # 1. Load cấu hình chuẩn của vgg_transformer
        config = Cfg.load_config_from_name('vgg_transformer')
        
        # 2. Tự động tải weights từ Hugging Face
        model_path = hf_hub_download(
            repo_id="DungHugging/vietocr-handwritten-finetune",
            filename="transformerocr.pth"
        )
        
        config['weights'] = model_path
        config['device'] = 'cpu' # VPS thường dùng CPU
        config['predictor']['beamsearch'] = False # Tăng tốc độ dự đoán
        
        # 3. Khởi tạo Predictor của thư viện vietocr
        self.predictor = Predictor(config)

    def predict(self, pil_img):
        # Trả về kết quả text trực tiếp
        return self.predictor.predict(pil_img)



class ModelLoader:
    """Singleton class để load và cache OCR model (DeepDoc + VietOCR)"""
    
    _instance = None
    _ocr = None
    _rembg_session = None
    _rembg_lock = threading.Lock()
    _handwritten_predictor = None
    _tts = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ModelLoader, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize ModelLoader (sử dụng cơ chế Lazy Load để cứu RAM cho API container)."""
        pass

    def preload_all_models(self):
        """Tải trước toàn bộ các model nặng (thường dùng cho Worker)."""
        Log.info("📦 Bắt đầu tải trước toàn bộ AI Models...")
        self._load_ocr()
        self._load_tts()
        # Tạm thời loại bỏ preload handwriting model khi run app bằng docker
        # self._load_handwritten()
        Log.info("✅ Hoàn tất tải trước toàn bộ AI Models!")

    def preload_photo_models(self, require_rembg: bool = False) -> bool:
        """
        Khởi tạo session photo ngay khi API worker boot để request đầu không phải
        trả chi phí load ONNX. Mỗi Gunicorn worker sở hữu session riêng.
        """
        Log.info("📦 Preloading photo models (MODNet + InsightFace)...")
        rembg_session = self._load_rembg()

        # Face analyzer cũng nằm trên synchronous photo route nên preload cùng lúc.
        try:
            from src.shared.utils.image_processing import get_face_analyzer
            face_analyzer = get_face_analyzer()
        except Exception as e:
            face_analyzer = None
            Log.error(f"❌ Failed to preload InsightFace: {e}")
            Log.error(traceback.format_exc())

        if rembg_session is None and require_rembg:
            raise RuntimeError("Không thể preload Rembg MODNet; API worker không được khởi động.")

        if face_analyzer is None:
            Log.warning("⚠️ InsightFace unavailable; photo route will use Haar fallback.")

        success = rembg_session is not None
        Log.info(
            f"✅ Photo model preload completed: rembg={rembg_session is not None}, "
            f"insightface={face_analyzer is not None}"
        )
        return success

    def _load_ocr(self):
        """Load DeepDoc + VietOCR engine"""
        if self._ocr is None:
            Log.info("📖 Loading DeepDoc + VietOCR OCR engine...")
            try:
                # Triển khai xác thực Hugging Face bằng Token
                hf_token = os.getenv("HF_TOKEN")
                if hf_token:
                    from huggingface_hub import login
                    login(token=hf_token)
                    Log.info("🔑 Hugging Face Hub authenticated successfully with HF_TOKEN!")
                
                from src.modules.ocr.deepdoc.ocr_engine import DeepDocOCR
                self._ocr = DeepDocOCR()
                Log.info("✅ DeepDoc + VietOCR loaded successfully!")
            except Exception as e:
                Log.error(f"❌ Failed to load DeepDoc OCR: {e}")
                Log.error(traceback.format_exc())
        return self._ocr

    def _load_rembg(self):
        """Khởi tạo và cache một Rembg MODNet session cho process hiện tại."""
        if self._rembg_session is None:
            with self._rembg_lock:
                if self._rembg_session is not None:
                    return self._rembg_session
                Log.info("🎨 Loading Rembg Model (modnet)...")
                try:
                    from rembg import new_session
                    self._rembg_session = new_session("modnet")
                    Log.info("✅ Rembg Model (modnet) loaded success!")
                except Exception as e:
                    Log.error(f"❌ Failed to load Rembg Model: {e}")
                    Log.error(traceback.format_exc())
        return self._rembg_session

    def _load_handwritten(self):
        """Load VietOCR Handwritten model from Hugging Face"""
        if self._handwritten_predictor is None:
            try:
                self._handwritten_predictor = VietOCRHandwrittenPredictor()
                Log.info("✅ Handwritten OCR loaded successfully from Hugging Face!")
            except Exception as e:
                Log.error(f"❌ Failed to load Handwritten OCR: {e}")
                Log.error(traceback.format_exc())
        return self._handwritten_predictor

    def _load_tts(self):
        """Load VieNeu-TTS model cho chức năng Text-to-Speech & Voice Cloning"""
        if self._tts is None:
            Log.info("🗣️ Loading VieNeu-TTS model...")
            try:
                from vieneu import Vieneu
                self._tts = Vieneu()
                Log.info("✅ VieNeu-TTS loaded successfully!")
            except Exception as e:
                Log.error(f"❌ Failed to load VieNeu-TTS: {e}")
                Log.error(traceback.format_exc())
        return self._tts

    @property
    def ocr(self):
        """Get OCR instance (DeepDocOCR), loading if necessary"""
        if self._ocr is None:
            self._load_ocr()
        return self._ocr

    @property
    def device(self):
        """Get device, always cpu for DeepDoc+VietOCR"""
        return "cpu"

    @property
    def rembg_session(self):
        """Get preloaded MODNet session; lazy fallback giữ tương thích ngoài Gunicorn."""
        return self._load_rembg()

    @property
    def handwritten_predictor(self):
        """Get handwritten OCR predictor instance, loading if necessary"""
        if self._handwritten_predictor is None:
            self._load_handwritten()
        return self._handwritten_predictor

    @property
    def tts(self):
        """Get VieNeu-TTS instance (đã được preload sẵn khi khởi động)"""
        if self._tts is None:
            self._load_tts()
        return self._tts


# Global instance
model_loader = ModelLoader()
