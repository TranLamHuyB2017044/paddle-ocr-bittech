"""
TTS Module Initializer
Package initializer exporting tts_bp blueprint for Flask auto-registration.
"""
from src.modules.tts.routes import tts_bp

__all__ = ["tts_bp"]
