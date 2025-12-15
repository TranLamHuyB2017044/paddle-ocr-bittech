from datetime import datetime, timedelta
from app.models.user import User
from app.models.auth_session import AuthSession
from app.repositories.users_repository import users_repo
from app.repositories.auth_repository import auth_repo
from app.utils.security import (
    hash_password, verify_password, 
    create_access_token, create_refresh_token, hash_token
)
from app.config import REFRESH_TOKEN_EXPIRE_DAYS

class AuthService:
    def register(self, username, email, password, fullname=None, phone=None):
        if users_repo.find_by_username(username):
            raise ValueError("Username already exists")
            
        # 2. Tạo user mới
        user = User(
            username=username,
            email=email,
            password=hash_password(password),
            fullname=fullname,
            phone=phone,
            auth_provider="local"
        )
        
        # 3. Lưu
        user_id = users_repo.create_user(user)
        return user_id

    def login(self, username, password, user_agent, ip, device_id=None):
        # 1. Tìm user
        user_data = users_repo.find_by_username(username)
        if not user_data:
            raise ValueError("Invalid username or password")
            
        # 2. Verify Pass
        # Parse về Pydantic model để dễ truy cập field
        user = User(**user_data)
        if not user.password or not verify_password(password, user.password):
             raise ValueError("Invalid username or password")

        # 3. Tạo Tokens
        access_token = create_access_token(str(user.id))
        refresh_token = create_refresh_token()
        
        # 4. Lưu Session
        refresh_hash = hash_token(refresh_token)
        expires_at = datetime.now() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        
        session = AuthSession(
            user_id=str(user.id),
            refresh_token_hash=refresh_hash,
            user_agent=user_agent,
            device_id=device_id,
            ip=ip,
            expires_at=expires_at
        )
        auth_repo.create_session(session)
        
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "user": {
                "id": str(user.id),
                "email": user.email,
                "fullname": user.fullname
            }
        }

    def reduce_refresh_token(self, old_refresh_token):
        """Dùng refresh token cũ để lấy access token mới"""
        # 1. Hash token gửi lên
        token_hash = hash_token(old_refresh_token)
        
        # 2. Tìm session
        session_data = auth_repo.find_by_hash(token_hash)
        if not session_data:
            raise ValueError("Invalid refresh token")
            
        session = AuthSession(**session_data)
        
        # 3. Validate
        if session.revoked:
            raise ValueError("Session revoked")
        if session.expires_at < datetime.now():
            raise ValueError("Refresh token expired")
            
        # 4. Cấp Access Token mới
        new_access_token = create_access_token(session.user_id)
        
        return {
            "access_token": new_access_token
        }

    def logout(self, refresh_token):
        token_hash = hash_token(refresh_token)
        auth_repo.revoke_session(token_hash)

auth_service = AuthService()
