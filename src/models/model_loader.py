"""
Model Loader
Load và quản lý DeepDoc + VietOCR models (không còn PaddleOCR)
"""
import os
import traceback
import numpy as np
import json
import onnxruntime as ort
from PIL import Image
from ..utils.logger import Log


class VietOCRONNXPredictor:
    def __init__(self, encoder_path, decoder_path, vocab_path):
        options = ort.SessionOptions()
        # options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        
        self.encoder_session = ort.InferenceSession(encoder_path, sess_options=options, providers=['CPUExecutionProvider'])
        self.decoder_session = ort.InferenceSession(decoder_path, sess_options=options, providers=['CPUExecutionProvider'])
        
        with open(vocab_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            self.i2c = data['i2c']
        
        self.max_seq_length = 128
        self.sos_token = 1
        self.eos_token = 2

    def preprocess(self, pil_img):
        # VietOCR standard preprocessing: resize to height 32, maintain aspect ratio
        w, h = pil_img.size
        new_w = int(32 * w / h)
        img = pil_img.convert('RGB')
        img = img.resize((new_w, 32))
        img = np.array(img).astype(np.float32) / 255.0
        # Normalize (standard VietOCR: mean 0.5, std 0.5)
        img = (img - 0.5) / 0.5
        img = img.transpose(2, 0, 1) # HWC -> CHW
        img = np.expand_dims(img, axis=0) # CHW -> BCHW
        return img

    def predict(self, pil_img):
        img = self.preprocess(pil_img)
        
        # Encoder
        encoder_input_name = self.encoder_session.get_inputs()[0].name
        encoder_outputs = self.encoder_session.run(None, {encoder_input_name: img})
        
        # Determine encoder outputs structure
        if len(encoder_outputs) == 2:
            encoder_out, hidden = encoder_outputs
        else:
            encoder_out = encoder_outputs[0]
            hidden = None

        # [FIX] Pad hoặc Trim encoder_out về đúng độ dài 64 mà model Decoder yêu cầu
        def pad_or_trim_src(features, target_len=64):
            src_len = features.shape[0]
            if src_len < target_len:
                # Pad zeros phía sau: (64-18, 1, 256)
                pad = np.zeros((target_len - src_len, features.shape[1], features.shape[2]), dtype=np.float32)
                return np.concatenate([features, pad], axis=0)
            elif src_len > target_len:
                # Trim nếu dài hơn
                return features[:target_len]
            return features

        encoder_out = pad_or_trim_src(encoder_out, target_len=64)
            
        translated_sentence = [self.sos_token]
        
        for _ in range(self.max_seq_length):
            curr_len = len(translated_sentence)
            
            # [FIX] Quay lại chuẩn (Seq, Batch) dựa trên Metadata của model
            tgt_fixed = np.zeros((self.max_seq_length, 1), dtype=np.int64)
            tgt_fixed[:curr_len, 0] = translated_sentence
            
            input_names = [i.name for i in self.decoder_session.get_inputs()]
            
            decoder_inputs = {}
            if "tgt" in input_names:
                decoder_inputs["tgt"] = np.ascontiguousarray(tgt_fixed)
            
            if "src" in input_names:
                decoder_inputs["src"] = np.ascontiguousarray(encoder_out)
            elif "memory" in input_names:
                decoder_inputs["memory"] = np.ascontiguousarray(encoder_out)
                
            # Tạm thời KHÔNG truyền tgt_key_padding_mask để tránh lỗi broadcast 128^3
            # if "tgt_key_padding_mask" in input_names:
            #     mask = np.ones((1, self.max_seq_length), dtype=bool)
            #     mask[0, :curr_len] = False
            #     decoder_inputs["tgt_key_padding_mask"] = mask

            # Fallback nếu không khớp tên
            if not decoder_inputs:
                decoder_inputs[input_names[0]] = np.ascontiguousarray(tgt_fixed)
                if len(input_names) > 1:
                    decoder_inputs[input_names[1]] = np.ascontiguousarray(encoder_out)

            outputs = self.decoder_session.run(None, decoder_inputs)
            # Ép kiểu về np.ndarray để tránh lỗi linting/type checking
            output = np.array(outputs[0])
            
            # Predict next token: Lấy logits tại vị trí cuối cùng của chuỗi THẬT (curr_len - 1)
            if output.ndim == 3:
                # Output thường là [Seq, Batch, Vocab]
                if output.shape[0] == self.max_seq_length:
                    last_token_logits = output[curr_len - 1, 0, :] 
                else: # Batch first [Batch, Seq, Vocab]
                    last_token_logits = output[0, curr_len - 1, :]
            else:
                last_token_logits = output[0]
            
            next_token = int(np.argmax(last_token_logits))
            
            if next_token == self.eos_token:
                break
                
            translated_sentence.append(next_token)
            
        # Decode tokens to string
        return "".join([self.i2c.get(str(t), "") for t in translated_sentence if t not in [self.sos_token, self.eos_token, 0]])



class ModelLoader:
    """Singleton class để load và cache OCR model (DeepDoc + VietOCR)"""
    
    _instance = None
    _ocr = None
    _rembg_session = None
    _handwritten_predictor = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(ModelLoader, cls).__new__(cls)
        return cls._instance
    
    def __init__(self):
        """Initialize ModelLoader (sử dụng cơ chế Lazy Load để cứu RAM cho API container)."""
        pass

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
                
                from ..deepdoc.ocr_engine import DeepDocOCR
                self._ocr = DeepDocOCR()
                Log.info("✅ DeepDoc + VietOCR loaded successfully!")
            except Exception as e:
                Log.error(f"❌ Failed to load DeepDoc OCR: {e}")
                Log.error(traceback.format_exc())
        return self._ocr

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

    def _load_handwritten(self):
        """Load VietOCR Handwritten ONNX model"""
        if self._handwritten_predictor is None:
            Log.info("📖 Loading Handwritten OCR model (ONNX)...")
            try:
                # Paths to ONNX models and vocab
                base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                hw_dir = os.path.join(base_dir, "hand_writting")
                
                encoder_path = os.path.join(hw_dir, "vietocr_encoder_sim.onnx")
                decoder_path = os.path.join(hw_dir, "vietocr_decoder_sim.onnx")
                vocab_path = os.path.join(hw_dir, "vocab.json")
                
                # Check if files exist
                for p in [encoder_path, decoder_path, vocab_path]:
                    if not os.path.exists(p):
                        raise FileNotFoundError(f"Missing ONNX file: {p}")

                self._handwritten_predictor = VietOCRONNXPredictor(encoder_path, decoder_path, vocab_path)
                Log.info("✅ Handwritten OCR (ONNX) loaded successfully!")
            except Exception as e:
                Log.error(f"❌ Failed to load Handwritten OCR (ONNX): {e}")
                Log.error(traceback.format_exc())
        return self._handwritten_predictor

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
        """Get rembg session (DISABLED by default)"""
        return self._rembg_session

    @property
    def handwritten_predictor(self):
        """Get handwritten OCR predictor instance, loading if necessary"""
        if self._handwritten_predictor is None:
            self._load_handwritten()
        return self._handwritten_predictor


# Global instance
model_loader = ModelLoader()
