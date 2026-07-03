"""
CCCD OCR API
Main Flask application - Refactored version
"""
from flask import Flask
from flask_cors import CORS
import os

import src.config as config
from src.api.routes import register_routes
from src.api.admin_routes import register_admin_routes
from src.utils.rate_limit import init_limiter
# Model loader is no longer explicitly imported here to prevent unnecessary loading


# ==================== FLASK APP SETUP ====================
# Serve static files from 'public' folder
app = Flask(__name__, static_folder='public', static_url_path='')
CORS(app)

# Khởi tạo Rate Limiter (dùng chung Redis hiện tại)
init_limiter(app)

# Initialize MongoDB Connection
from src.database import mongo

# Tạo thư mục upload
os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = config.UPLOAD_FOLDER

# Ensure JSON response keys are NOT sorted (preserve order)
if hasattr(app, 'json'):
    app.json.sort_keys = False # type: ignore
app.config['JSON_SORT_KEYS'] = False

# ==================== LOAD MODELS ====================
from src.utils.logger import Log
# Models will be loaded on-demand by the worker, not the API server
Log.info(f"📁 Upload folder: {config.UPLOAD_FOLDER}")

# Preload ResNet18 model for Product Recognition
try:
    from src.product_recognition.models import warmup_model
    Log.info("📖 Preloading ResNet18 model for Product Recognition...")
    warmup_model()
    Log.info("✅ ResNet18 model preloaded successfully!")
except Exception as e:
    Log.error(f"❌ Failed to preload ResNet18 model: {e}")

Log.info("="*70)


# ==================== REGISTER ROUTES ====================
register_routes(app)
register_admin_routes(app)

from src.api.sheet_routes import sheet_bp
from src.api.auth_routes import auth_bp
from src.rag.rag_routes import rag_bp
from src.api.sse_routes import sse_bp
from src.api.subscription_routes import subscription_bp
from src.api.email_routes import email_bp
from src.api.photo_routes import photo_bp
from src.api.file_routes import file_bp
from src.api.tts_routes import tts_bp
from src.api.public_chat_routes import public_chat_bp
from src.api.chatbot_routes import chatbot_bp
from src.product_recognition.routes.product_routes import product_bp
from src.api.crawl_routes import crawl_bp

app.register_blueprint(sheet_bp)
app.register_blueprint(auth_bp)
app.register_blueprint(rag_bp)
app.register_blueprint(sse_bp)
app.register_blueprint(subscription_bp)
app.register_blueprint(email_bp)
app.register_blueprint(photo_bp)
app.register_blueprint(file_bp)
app.register_blueprint(tts_bp)
app.register_blueprint(public_chat_bp)
app.register_blueprint(chatbot_bp)
app.register_blueprint(product_bp, url_prefix='/api')
app.register_blueprint(crawl_bp)


# Explicit route to serve files from public folder (registered after all other routes)
@app.route('/<path:filename>', methods=['GET'])
def serve_public_file(filename):
    from flask import send_from_directory
    import os
    # Check if file exists in public folder
    file_path = os.path.join('public', filename)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return send_from_directory('public', filename)
    # Otherwise, let Flask handle it (show 404 or other routes)
    return "Not found", 404

# ==================== RUN APP ====================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
