"""
CCCD OCR API
Main Flask application - Refactored version
"""
from flask import Flask
from flask_cors import CORS
import os

import src.config as config
from src.api.routes import register_routes
from src.models.model_loader import model_loader


# ==================== FLASK APP SETUP ====================
app = Flask(__name__)
CORS(app)

# Initialize MongoDB Connection
from src.database import mongo

# Tạo thư mục upload
os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = config.UPLOAD_FOLDER

# Ensure JSON response keys are NOT sorted (preserve order)
app.json.sort_keys = False
app.config['JSON_SORT_KEYS'] = False

# ==================== LOAD MODELS ====================
from src.utils.logger import Log

# ==================== LOAD MODELS ====================
Log.info("="*70)
Log.info("🚀 KHỞI ĐỘNG CCCD OCR API")
Log.info("="*70)

# Models sẽ được load tự động khi import model_loader
Log.info(f"✅ Models đã sẵn sàng!")
Log.info(f"📁 Upload folder: {config.UPLOAD_FOLDER}")
Log.info("="*70)


# ==================== REGISTER ROUTES ====================
register_routes(app)

from src.api.sheet_routes import sheet_bp
from src.api.auth_routes import auth_bp
app.register_blueprint(sheet_bp)
app.register_blueprint(auth_bp)

# ==================== RUN APP ====================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
