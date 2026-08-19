"""
Modules Package Initializer
Central registration point for feature modules in Clean Architecture.
"""
from flask import Flask
from src.utils.logger import Log


def register_modules(app: Flask) -> None:
    """
    Auto-registers all feature module blueprints to the Flask application.
    """
    # 1. Image Processing Module
    try:
        from src.modules.image_processing.routes import photo_bp
        app.register_blueprint(photo_bp)
        Log.info("  └─ Registered module: [image_processing]")
    except Exception as e:
        Log.error(f"❌ Failed to register image_processing module: {e}")

    # 2. Text-To-Speech (TTS) Module
    try:
        from src.modules.tts.routes import tts_bp
        app.register_blueprint(tts_bp)
        Log.info("  └─ Registered module: [tts]")
    except Exception as e:
        Log.error(f"❌ Failed to register tts module: {e}")

    # 3. Document OCR Module
    try:
        from src.modules.ocr.routes import file_bp
        app.register_blueprint(file_bp)
        Log.info("  └─ Registered module: [ocr]")
    except Exception as e:
        Log.error(f"❌ Failed to register ocr module: {e}")

    # 4. DOCX Document Module
    try:
        from src.modules.docx.routes import docx_bp
        app.register_blueprint(docx_bp)
        Log.info("  └─ Registered module: [docx]")
    except Exception as e:
        Log.error(f"❌ Failed to register docx module: {e}")

    # 5. Chatbot Module
    try:
        from src.modules.chatbot.routes import chatbot_bp
        app.register_blueprint(chatbot_bp)
        Log.info("  └─ Registered module: [chatbot]")
    except Exception as e:
        Log.error(f"❌ Failed to register chatbot module: {e}")

    # 6. Auth & Admin License Module
    try:
        from src.modules.auth.routes import auth_bp
        app.register_blueprint(auth_bp)
        Log.info("  └─ Registered module: [auth]")
    except Exception as e:
        Log.error(f"❌ Failed to register auth module: {e}")

    # 7. Integrations (Crawl) Module
    try:
        from src.modules.integrations.routes import crawl_bp
        app.register_blueprint(crawl_bp)
        Log.info("  └─ Registered module: [integrations]")
    except Exception as e:
        Log.error(f"❌ Failed to register integrations module: {e}")
