"""
Product Recognition Module
Nhận dạng sản phẩm sử dụng ResNet18 và Qdrant
"""
from src.modules.product_recognition.routes.product_routes import product_bp

__all__ = ["product_bp"]
