"""
Auth Module Initializer
Package initializer exporting auth_bp blueprint for Flask auto-registration.
"""
from src.modules.auth.routes import auth_bp

__all__ = ["auth_bp"]
