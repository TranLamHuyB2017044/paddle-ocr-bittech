"""
CCCD OCR API
Main Flask application - Refactored version
"""
from flask import Flask
from flask_cors import CORS
import os

from cccd.config import UPLOAD_FOLDER
from cccd.api.routes import register_routes
from cccd.models.model_loader import model_loader


# ==================== FLASK APP SETUP ====================
app = Flask(__name__)
CORS(app)

# Tạo thư mục upload
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# ==================== LOAD MODELS ====================
print("="*70)
print("🚀 KHỞI ĐỘNG CCCD OCR API")
print("="*70)

# Models sẽ được load tự động khi import model_loader
print(f"✅ Models đã sẵn sàng!")
print(f"📁 Upload folder: {UPLOAD_FOLDER}")
print("="*70)
print()

# ==================== REGISTER ROUTES ====================
register_routes(app)

# ==================== RUN APP ====================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
