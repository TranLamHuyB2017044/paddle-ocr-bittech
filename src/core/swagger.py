"""Swagger documentation configuration, independent of application services."""
from pathlib import Path

from flasgger import Swagger, swag_from
import yaml


DOCS_DIR = Path(__file__).resolve().parents[2] / "docs" / "api"


def load_api_specs():
    """Read reviewed operation specs, keyed by Flask endpoint name."""
    specs = {}
    for path in sorted((DOCS_DIR / "modules").glob("*.yml")):
        with path.open(encoding="utf-8") as source:
            operations = yaml.safe_load(source)
        for endpoint, operation in operations.items():
            if endpoint in specs:
                raise ValueError(f"Duplicate API documentation: {endpoint}")
            specs[endpoint] = operation
    return specs


def _api_rules(app):
    """Exclude rules fully shadowed by earlier URL/method registrations."""
    rules = set()
    seen = set()
    for rule in app.url_map.iter_rules():
        if not (rule.rule == "/" or rule.rule.startswith("/api/") or rule.rule == "/send-email"):
            continue
        operations = {(rule.rule, method) for method in rule.methods - {"HEAD", "OPTIONS"}}
        if operations - seen:
            rules.add(id(rule))
        seen.update(operations)
    return rules


def init_swagger(app):
    """Expose Swagger UI and its JSON specification on the Flask app."""
    for endpoint, operation in load_api_specs().items():
        if endpoint in app.view_functions:
            documented_view = swag_from(operation)(app.view_functions[endpoint])
            # Flasgger otherwise merges the original prose docstring over the
            # reviewed summary/description. The original remains on __wrapped__.
            documented_view.__doc__ = ""
            app.view_functions[endpoint] = documented_view
    rules = _api_rules(app)
    return Swagger(
        app,
        config={
            "headers": [],
            "specs": [{
                "endpoint": "api_spec",
                "route": "/api-doc/swagger.json",
                "rule_filter": lambda rule: id(rule) in rules,
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
                "description": "Bittech API: authentication, OCR, photos, TTS, chatbot, RAG, integrations and administration. Most protected APIs use x-api-key; public chatbot APIs use x-public-token.",
            },
            "securityDefinitions": {
                "ApiKeyAuth": {"type": "apiKey", "name": "x-api-key", "in": "header"},
                "PublicTokenAuth": {"type": "apiKey", "name": "x-public-token", "in": "header"},
                "GoogleBearerAuth": {
                    "type": "apiKey", "name": "Authorization", "in": "header",
                    "description": "Google access token for saving to Sheets. Enter: Bearer <token>.",
                },
            },
            "definitions": {
                "ApiError": {
                    "type": "object",
                    "description": "Error fields vary by endpoint and service.",
                    "properties": {
                        "statusCode": {"type": "integer"},
                        "message": {"type": "string"},
                        "error": {},
                        "detail": {"type": "string"},
                    },
                    "additionalProperties": True,
                },
            },
            "tags": [
                {"name": "Health", "description": "Service health"},
                {"name": "OCR", "description": "Document recognition and results"},
                {"name": "Auth", "description": "Authentication and external connections"},
                {"name": "Users", "description": "Profiles and user accounts"},
                {"name": "Documents", "description": "Extraction history and corrections"},
                {"name": "Photos", "description": "Portrait processing and cropping"},
                {"name": "TTS", "description": "Text to speech"},
                {"name": "Chatbot", "description": "Chatbot management"},
                {"name": "Public Chatbot", "description": "Chatbot access using public tokens"},
                {"name": "Categories", "description": "Workspace categories and audit logs"},
                {"name": "RAG", "description": "Workspaces, documents and retrieval"},
                {"name": "Records", "description": "External document record synchronization"},
                {"name": "Subscriptions", "description": "Plans, quotas and usage"},
                {"name": "Admin", "description": "Administration; role restrictions apply"},
                {"name": "Integrations", "description": "Crawling, email and Google Sheets"},
                {"name": "Products", "description": "Product recognition and training"},
                {"name": "Events", "description": "Server-sent event stream"},
            ],
        },
    )
