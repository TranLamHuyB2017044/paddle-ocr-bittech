import requests
import trafilatura
from typing import Dict, Any, Tuple
from urllib.parse import urlparse
from src.services.metadata_service import metadata_service
from src.utils.logger import Log

class CrawlerService:
    @staticmethod
    def crawl_url(url: str, timeout: int = 10) -> Tuple[bool, Dict[str, Any], str]:
        """
        Crawl the URL, extract content, and compile metadata.
        Returns:
            Tuple of (success: bool, data_dict: Dict, error_message: str)
        """
        html = None
        
        # Parse host domain for fallback and response
        try:
            parsed_url = urlparse(url)
            source_domain = parsed_url.netloc
            if source_domain.startswith("www."):
                source_domain = source_domain[4:]
        except Exception:
            source_domain = ""

        # Step 2: Download HTML using requests with timeout
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5"
        }
        
        try:
            Log.info(f"[Crawler Service] Fetching URL: {url} (Timeout: {timeout}s)")
            response = requests.get(url, headers=headers, timeout=timeout, allow_redirects=True)
            if response.status_code == 200:
                html = response.text
            else:
                Log.warning(f"[Crawler Service] Requests returned status {response.status_code}. Retrying with trafilatura.fetch_url.")
        except Exception as e:
            Log.warning(f"[Crawler Service] Requests failed to fetch {url}: {e}. Retrying with trafilatura.fetch_url.")

        # Fallback to trafilatura.fetch_url if requests failed or returned non-200
        if not html:
            try:
                html = trafilatura.fetch_url(url)
            except Exception as e:
                Log.error(f"[Crawler Service] Trafilatura fetch_url failed for {url}: {e}")
                return False, {}, f"Failed to fetch content: {str(e)}"

        if not html:
            return False, {}, "Failed to download HTML content from the URL."

        # Step 3: Extract main content using trafilatura
        try:
            content = trafilatura.extract(
                html,
                output_format="txt",
                include_comments=False,
                include_tables=True,
                include_links=True,
                no_fallback=False
            )
        except Exception as e:
            Log.error(f"[Crawler Service] Trafilatura extract error: {e}")
            content = None

        # Playwright Fallback if no content extracted (commonly SPA/Javascript-heavy site)
        if not content or len(content.strip()) < 50:
            Log.info(f"[Crawler Service] Empty or short content. Attempting Playwright fallback for: {url}")
            rendered_html = CrawlerService._crawl_with_playwright(url, timeout)
            if rendered_html:
                try:
                    rendered_content = trafilatura.extract(
                        rendered_html,
                        output_format="txt",
                        include_comments=False,
                        include_tables=True,
                        include_links=True,
                        no_fallback=False
                    )
                    # If Playwright successfully extracted text content, use it and update html reference
                    if rendered_content and len(rendered_content.strip()) >= len(content or ""):
                        content = rendered_content
                        html = rendered_html
                        Log.info("[Crawler Service] Playwright fallback succeeded in extracting text.")
                except Exception as e:
                    Log.error(f"[Crawler Service] Trafilatura extract error on Playwright HTML: {e}")

        # Step 4: Extract Metadata using MetadataService
        try:
            metadata = metadata_service.extract_metadata(html)
        except Exception as e:
            Log.error(f"[Crawler Service] Metadata extraction error: {e}")
            metadata = {
                "title": "",
                "description": "",
                "thumbnail": "",
                "author": "",
                "published_at": "",
                "language": "",
                "keywords": []
            }

        # Validate extraction results
        # If both title and content could not be extracted, the crawl is considered failed
        if not content and not metadata.get("title"):
            return False, {}, "Unable to extract content"

        # Step 5: Normalize and build data structure
        normalized_data = {
            "title": metadata.get("title") or "",
            "description": metadata.get("description") or "",
            "content": content or "",
            "thumbnail": metadata.get("thumbnail") or "",
            "source_url": url,
            "source_domain": source_domain,
            "crawl_at": "", # Will be filled by router / repository during save
            # Version 2 metadata
            "author": metadata.get("author") or "",
            "published_at": metadata.get("published_at") or "",
            "language": metadata.get("language") or "",
            "keywords": metadata.get("keywords") or []
        }

        return True, normalized_data, ""

    @staticmethod
    def _crawl_with_playwright(url: str, timeout: int) -> str | None:
        """
        Fallback mechanism using Playwright to render SPA / Javascript-heavy web pages.
        Returns:
            Fully rendered HTML string or None if failed / not installed.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            Log.warning("[Crawler Service] Playwright library not found in Python env. Skipping Playwright fallback.")
            return None

        try:
            Log.info(f"[Crawler Service] Running Playwright sync crawler for: {url}")
            with sync_playwright() as p:
                # Launch Chromium in headless mode
                browser = p.chromium.launch(headless=True)
                # Set viewport and user-agent to mock a desktop browser
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800}
                )
                page = context.new_page()
                
                # Navigate to the target page with timeout (converted to milliseconds)
                page.goto(url, timeout=timeout * 1000, wait_until="networkidle")
                
                # Fetch fully rendered DOM HTML
                html_content = page.content()
                browser.close()
                return html_content
        except Exception as e:
            Log.error(f"[Crawler Service] Playwright rendering failed: {e}")
            return None

# Global instance
crawler_service = CrawlerService()

