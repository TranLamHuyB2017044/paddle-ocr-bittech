"""Swagger documentation configuration, independent of application services."""
from pathlib import Path

from flasgger import Swagger


DOCS_DIR = Path(__file__).resolve().parents[2] / "docs" / "api"


def init_swagger(app):
    """Expose Swagger UI and its JSON specification on the Flask app."""
    return Swagger(
        app,
        config={
            "headers": [],
            "specs": [{
                "endpoint": "api_spec",
                "route": "/api-doc/swagger.json",
                "rule_filter": lambda rule: rule.rule == "/" or rule.rule.startswith("/api/"),
                "model_filter": lambda tag: True,
            }],
            "static_url_path": "/flasgger_static",
            "swagger_ui": True,
            "specs_route": "/api-doc/",
        },
        template={
            "swagger": "2.0",
            "info": {
                "title": "Bittech OCR API",
                "version": "1.0.0",
                "description": "Initial documentation: health check and OCR document status.",
            },
            "securityDefinitions": {
                "ApiKeyAuth": {"type": "apiKey", "name": "x-api-key", "in": "header"},
            },
            "tags": [
                {"name": "Health", "description": "Service health"},
                {"name": "OCR", "description": "Document recognition and results"},
            ],
        },
    )
