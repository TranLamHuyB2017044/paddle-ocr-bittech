"""
CCCD OCR API
Main Flask application - Refactored version
"""
from flask import Flask
from flask_cors import CORS
import os

import src.config as config
from src.api.routes import register_routes
from src.utils.rate_limit import init_limiter
# Model loader is no longer explicitly imported here to prevent unnecessary loading


# ==================== FLASK APP SETUP ====================
app = Flask(__name__)
CORS(app)

# Khởi tạo Rate Limiter (dùng chung Redis hiện tại)
init_limiter(app)

# Initialize MongoDB Connection
from src.database import mongo

# Tạo thư mục upload
os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = config.UPLOAD_FOLDER

# ==================== INITIALIZE RATE LIMITER ====================
limiter = init_limiter(app)

# Ensure JSON response keys are NOT sorted (preserve order)
app.json.sort_keys = False
app.config['JSON_SORT_KEYS'] = False

# ==================== LOAD MODELS ====================
from src.utils.logger import Log

# Models will be loaded on-demand by the worker, not the API server
Log.info(f"📁 Upload folder: {config.UPLOAD_FOLDER}")
Log.info("="*70)


# ==================== REGISTER ROUTES ====================
register_routes(app)

from src.api.sheet_routes import sheet_bp
from src.api.auth_routes import auth_bp
from src.rag.rag_routes import rag_bp
from src.api.sse_routes import sse_bp
from src.api.subscription_routes import subscription_bp
from src.api.email_routes import email_bp
from src.api.photo_routes import photo_bp
from src.api.file_routes import file_bp

app.register_blueprint(sheet_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(rag_bp)
app.register_blueprint(sse_bp)
app.register_blueprint(subscription_bp)
app.register_blueprint(email_bp)
app.register_blueprint(photo_bp)
app.register_blueprint(file_bp)

# ==================== RUN APP ====================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
