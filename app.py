"""
CCCD OCR API
Main Flask application - Clean Architecture version
"""
from flask import Flask
from flask_cors import CORS
from flasgger import swag_from
import os

import src.core.config as config
from src.shared.utils.rate_limit import init_limiter
from src.core.swagger import DOCS_DIR, init_swagger


# ==================== FLASK APP SETUP ====================
# Serve static files from 'public' folder
app = Flask(__name__, static_folder='public', static_url_path='')
CORS(app)

# Khởi tạo Rate Limiter
init_limiter(app)

# ==================== REGISTER ROUTES ====================
@app.route("/", methods=["GET"])
@swag_from(str(DOCS_DIR / "health.yml"))
def health_check():
    from flask import jsonify
    return jsonify({"status": "ok", "message": "CCCD OCR API is running"}), 200

# Initialize MongoDB Connection
from src.core.database import mongo

# Tạo thư mục upload
os.makedirs(config.UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = config.UPLOAD_FOLDER

# Ensure JSON response keys are NOT sorted (preserve order)
if hasattr(app, 'json'):
    app.json.sort_keys = False # type: ignore
app.config['JSON_SORT_KEYS'] = False

# ==================== LOAD MODELS ====================
from src.shared.utils.logger import Log
Log.info(f"📁 Upload folder: {config.UPLOAD_FOLDER}")

# Preload ResNet18 model for Product Recognition
try:
    from src.modules.product_recognition.models import warmup_model
    Log.info("📖 Preloading ResNet18 model for Product Recognition...")
    warmup_model()
    Log.info("✅ ResNet18 model preloaded successfully!")
except Exception as e:
    Log.error(f"❌ Failed to preload ResNet18 model: {e}")

Log.info("="*70)


# ==================== REGISTER ROUTES ====================
# Register Clean Architecture Feature Modules (image_processing, tts, ocr, docx, chatbot, auth)
from src.modules import register_modules
register_modules(app)

# Register Other Blueprints
from src.modules.rag.rag_routes import rag_bp
from src.modules.chatbot.category_routes import category_bp
from src.core.sse.routes import sse_bp
from src.modules.product_recognition.routes.product_routes import product_bp

app.register_blueprint(rag_bp)
app.register_blueprint(category_bp)
app.register_blueprint(sse_bp)
app.register_blueprint(product_bp, url_prefix='/api')

init_swagger(app)


# Explicit route to serve files from public folder (registered after all other routes)
@app.route('/<path:filename>', methods=['GET'])
def serve_public_file(filename):
    from flask import send_from_directory
    file_path = os.path.join('public', filename)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return send_from_directory('public', filename)
    return "Not found", 404


# ==================== RUN APP ====================
if __name__ == "__main__":
    from src.shared.models.model_loader import model_loader
    model_loader.preload_photo_models(require_rembg=True)
    app.run(host="0.0.0.0", port=5000, debug=True)
