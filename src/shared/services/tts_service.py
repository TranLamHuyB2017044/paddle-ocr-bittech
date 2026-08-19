"""
TTS Service Compatibility Shim
Redirects to src.modules.tts.services
"""
from src.modules.tts.services import TTSService, tts_service

__all__ = ["TTSService", "tts_service"]
