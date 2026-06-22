from flask import Blueprint, request, jsonify
from src.utils.rate_limit import get_limiter
from src.utils.ssrf_protection import is_safe_url
from src.utils.crawl_logger import log_crawl
from src.services.crawler_service import crawler_service
from src.repositories.articles_repository import articles_repo
from src.utils.logger import Log
from datetime import datetime
import time

crawl_bp = Blueprint('crawl_bp', __name__)
limiter = get_limiter()

@crawl_bp.route('/api/v1/crawl', methods=['POST'])
@limiter.limit("100 per minute")
def crawl_url_endpoint():
    """
    POST /api/v1/crawl
    Crawl and extract article contents from a URL.
    """
    start_time = time.perf_counter()
    
    # 1. Parse JSON payload
    data_json = request.get_json(silent=True)
    if not data_json or 'url' not in data_json:
        return jsonify({
            "success": False,
            "message": "Missing 'url' parameter"
        }), 400
        
    url = data_json['url'].strip()

    # 2. Validate URL and Protect against SSRF
    if not is_safe_url(url):
        log_crawl(url, "FAILED", error="SSRF_OR_INVALID_URL")
        return jsonify({
            "success": False,
            "message": "Unable to extract content"
        }), 200

    # 3. Crawl using service (enforcing 10s timeout inside crawler_service)
    try:
        success, crawl_data, error_msg = crawler_service.crawl_url(url, timeout=10)
    except Exception as e:
        duration_ms = (time.perf_counter() - start_time) * 1000
        log_crawl(url, "FAILED", duration_ms=duration_ms, error=str(e))
        return jsonify({
            "success": False,
            "message": "Unable to extract content"
        }), 200

    duration_ms = (time.perf_counter() - start_time) * 1000

    if not success:
        log_crawl(url, "FAILED", duration_ms=duration_ms, error=error_msg or "EXTRACTION_FAILED")
        return jsonify({
            "success": False,
            "message": error_msg or "Unable to extract content"
        }), 200

    # 4. Set crawl time and save to database
    crawl_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    crawl_data["crawl_at"] = crawl_time

    try:
        articles_repo.create_article(
            title=crawl_data["title"],
            description=crawl_data["description"],
            content=crawl_data["content"],
            thumbnail=crawl_data["thumbnail"],
            source_url=crawl_data["source_url"],
            source_domain=crawl_data["source_domain"],
            crawl_at=crawl_data["crawl_at"],
            author=crawl_data["author"],
            published_at=crawl_data["published_at"],
            language=crawl_data["language"],
            keywords=crawl_data["keywords"]
        )
    except Exception as e:
        Log.error(f"[Crawl Router] Failed to save article to MongoDB: {e}")
        log_crawl(url, "FAILED", duration_ms=duration_ms, error=f"DATABASE_SAVE_FAILED: {e}")
        return jsonify({
            "success": False,
            "message": "Unable to save source information to database"
        }), 200

    # Log success to structured JSON logs
    log_crawl(url, "SUCCESS", duration_ms=duration_ms)

    return jsonify({
        "success": True,
        "data": {
            "title": crawl_data["title"],
            "description": crawl_data["description"],
            "content": crawl_data["content"],
            "thumbnail": crawl_data["thumbnail"],
            "source_url": crawl_data["source_url"],
            "source_domain": crawl_data["source_domain"],
            "crawl_at": crawl_data["crawl_at"]
        }
    }), 200
