"""
Chatbot Module Initializer
Exposes chatbot_bp blueprint for Flask auto-registration.
"""
from src.modules.chatbot.routes import chatbot_bp

__all__ = ["chatbot_bp"]
