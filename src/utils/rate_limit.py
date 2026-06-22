from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from src.config import REDIS_URL

import redis
from src.utils.logger import Log

# Kiểm tra Redis online, nếu offline tự động fallback về memory:// để chạy local không lỗi
storage_uri = REDIS_URL
try:
    r = redis.from_url(REDIS_URL, socket_connect_timeout=1, socket_timeout=1)
    r.ping()
except Exception:
    Log.warning("[Rate Limiter] Redis is offline. Falling back to in-memory rate limiting (memory://).")
    storage_uri = "memory://"

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=storage_uri,
    strategy="fixed-window",
    default_limits=["5000 per day", "1000 per hour", "100 per minute"],
    storage_options={
        "socket_connect_timeout": 5,
        "socket_timeout": 5,
    }
)



def init_limiter(app):
    """
    Gắn limiter vào Flask app lúc startup (dùng pattern init_app chuẩn).
    Gọi hàm này sau khi tạo app, trước khi nhận request đầu tiên.
    """
    limiter.init_app(app)
    return limiter


def get_limiter():
    """Lấy limiter instance (backward-compat)."""
    return limiter
