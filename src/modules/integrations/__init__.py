"""
Integrations Module Initializer
Exposes crawl_bp blueprint for Flask auto-registration.
"""
from src.modules.integrations.routes import crawl_bp

__all__ = ["crawl_bp"]
