"""
Modules Package
Clean Architecture Feature Modules registration
"""
from flask import Flask


def register_modules(app: Flask) -> None:
    """
    Register all feature module blueprints to the Flask application.
    """
    from src.modules.auth.routes import auth_bp
    from src.modules.ocr.routes import file_bp
    from src.modules.image_processing.routes import photo_bp
    from src.modules.tts.routes import tts_bp
    from src.modules.docx.routes import docx_bp
    from src.modules.chatbot.routes import chatbot_bp
    from src.modules.integrations.routes import crawl_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(file_bp)
    app.register_blueprint(photo_bp)
    app.register_blueprint(tts_bp)
    app.register_blueprint(docx_bp)
    app.register_blueprint(chatbot_bp)
    app.register_blueprint(crawl_bp)
