"""
TTS Service
Sử dụng VieNeu-TTS model đã được preload sẵn từ ModelLoader
để tổng hợp giọng nói và nhân bản giọng nói tức thì.
"""
import os
import uuid
import tempfile
from typing import List, Tuple, Optional
from src.shared.utils.logger import Log
from src.shared.models.model_loader import model_loader


class TTSService:
    """Service xử lý Text-to-Speech, lấy model từ ModelLoader (đã preload)."""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(TTSService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        pass

    def synthesize(self, text: str, voice_sample_path: Optional[str] = None, voice_name: Optional[str] = None) -> str:
        """
        Tổng hợp giọng nói từ text sử dụng VieNeu-TTS.
        Hỗ trợ trích xuất đặc trưng giọng mẫu (Zero-shot cloning) hoặc sử dụng preset voice.
        Trả về đường dẫn file âm thanh WAV tạm thời.
        """
        try:
            # Lấy model TTS đã được preload sẵn từ ModelLoader
            tts = model_loader.tts
            if tts is None:
                raise RuntimeError("VieNeu-TTS model chưa được tải. Vui lòng kiểm tra log khởi động.")

            voice = None
            if voice_sample_path and os.path.exists(voice_sample_path):
                Log.info(f"🎤 Đang trích xuất đặc trưng giọng mẫu từ: {voice_sample_path}")
                try:
                    voice = tts.encode_reference(voice_sample_path)
                except Exception as e:
                    Log.error(f"❌ Không thể mã hóa giọng mẫu, sử dụng giọng mặc định: {e}")
                    voice = None
            elif voice_name:
                Log.info(f"🎤 Đang lấy preset voice: {voice_name}")
                try:
                    voice = tts.get_preset_voice(voice_name)
                except Exception as e:
                    Log.error(f"❌ Không thể lấy preset voice '{voice_name}': {e}")
                    voice = None

            Log.info(f"🗣️ Đang sinh giọng đọc cho câu: '{text[:50]}...'")
            if voice is not None:
                audio = tts.infer(text=text, voice=voice)
            else:
                audio = tts.infer(text=text)

            # Tạo file tạm trong thư mục temp của hệ thống
            temp_dir = tempfile.gettempdir()
            filename = f"tts_{uuid.uuid4().hex[:8]}.wav"
            output_path = os.path.join(temp_dir, filename)
            Log.info(f"💾 Đang lưu file âm thanh WAV gốc vào: {output_path}")
            tts.save(audio, output_path)
            return output_path
        except Exception as e:
            Log.error(f"❌ Lỗi trong quá trình tổng hợp giọng nói: {e}")
            raise e

    def list_preset_voices(self) -> List[Tuple[str, str]]:
        """
        Lấy danh sách các giọng nói mẫu (preset voices) sẵn có từ model.
        """
        try:
            tts = model_loader.tts
            if tts is None:
                raise RuntimeError("VieNeu-TTS model chưa được tải. Vui lòng kiểm tra log khởi động.")

            # Trả về danh sách tuples: [(description, voice_id), ...]
            return tts.list_preset_voices()
        except Exception as e:
            Log.error(f"❌ Lỗi khi lấy danh sách preset voices: {e}")
            raise e


# Khởi tạo instance toàn cục
tts_service = TTSService()
