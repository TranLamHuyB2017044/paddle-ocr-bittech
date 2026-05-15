from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from src.config import REDIS_URL

# Global limiter instance (sẽ được khởi tạo trong app.py)
limiter = None

def init_limiter(app):
    """
    Khởi tạo Flask-Limiter với Redis backend (dùng chung Redis hiện tại)
    """
    global limiter
    
    limiter = Limiter(
        get_remote_address,
        app=app,
        storage_uri=REDIS_URL,
        strategy="fixed-window",
        default_limits=["5000 per day", "1000 per hour", "100 per minute"], 
        enabled=True, 
        storage_options={
            "socket_connect_timeout": 5,
            "socket_timeout": 5,
        }
    )
    
    return limiter

def get_limiter():
    """
    Lấy instance limiter (dùng trong các blueprint)
    """
    return limiter
