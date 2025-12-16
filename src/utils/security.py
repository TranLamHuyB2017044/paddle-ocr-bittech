import bcrypt
import jwt
import hashlib
import secrets
from datetime import datetime, timedelta
from src.config import JWT_SECRET_KEY, JWT_ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES

def hash_password(password: str) -> str:
    """Hash mật khẩu bằng bcrypt"""
    path_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(path_bytes, salt).decode('utf-8')

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Kiểm tra mật khẩu"""
    plain_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(plain_bytes, hashed_bytes)

def create_access_token(user_id: str, claims: dict = None) -> str:
    """Tạo JWT Access Token ngắn hạn"""
    if claims is None:
        claims = {}
    
    expire = datetime.now() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode = claims.copy()
    to_encode.update({
        "sub": user_id,
        "exp": expire,
        "type": "access"
    })
    
    return jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def create_refresh_token() -> str:
    """Tạo Refresh Token ngẫu nhiên (Opaque Token)"""
    return secrets.token_hex(32)

def hash_token(token: str) -> str:
    """Hash Refresh Token bằng SHA256 để lưu vào DB"""
    return hashlib.sha256(token.encode()).hexdigest()

def decode_access_token(token: str):
    """Giải mã JWT"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        return None # Hết hạn
    except jwt.InvalidTokenError:
        return None # Token sai
