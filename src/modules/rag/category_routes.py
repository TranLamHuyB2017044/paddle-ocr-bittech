# Re-export from chatbot module for backward compatibility
from src.modules.chatbot.category_routes import category_bp

__all__ = ["category_bp"]
