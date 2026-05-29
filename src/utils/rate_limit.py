from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from src.config import REDIS_URL

# Tạo limiter ở module-level — KHÔNG cần app lúc này.
# Decorator @limiter.limit(...) chỉ ghi metadata vào function,
# không kết nối Redis, nên an toàn khi import trong blueprint.
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=REDIS_URL,
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
