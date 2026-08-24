"""
Crawl Logger Utility
Logs crawl events to console and appends structured entries to logs/crawl.json.log.
"""
import os
import json
import threading
from typing import Optional, Any
from src.shared.utils.logger import Log

_log_lock = threading.Lock()


def log_crawl(url: str, status: str, duration_ms: Optional[float] = None, error: Optional[str] = None):
    """
    Log crawl result in structured JSON format.
    Appends to logs/crawl.json.log.
    """
    log_data: dict[str, Any] = {
        "url": url,
        "status": status.upper()
    }
    
    if duration_ms is not None:
        log_data["duration_ms"] = int(duration_ms)
        
    if error is not None:
        log_data["error"] = error

    # Log to our primary system logs
    log_msg = f"[Crawl Logger] {status.upper()} | URL: {url}"
    if duration_ms is not None:
        log_msg += f" | Duration: {int(duration_ms)}ms"
    if error is not None:
        log_msg += f" | Error: {error}"
    
    if status.upper() == "SUCCESS":
        Log.info(log_msg)
    else:
        Log.error(log_msg)

    # Log to JSON log file
    os.makedirs("logs", exist_ok=True)
    log_file_path = os.path.join("logs", "crawl.json.log")
    
    try:
        with _log_lock:
            with open(log_file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(log_data) + "\n")
    except Exception as e:
        Log.error(f"[Crawl Logger] Failed to write to {log_file_path}: {e}")
