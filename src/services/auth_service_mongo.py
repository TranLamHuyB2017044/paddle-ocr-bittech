from datetime import datetime, timedelta
from src.models.user import User
from src.models.auth_session import AuthSession
from src.repositories.users_repository import users_repo
from src.repositories.auth_repository import auth_repo
from src.utils.security import (
    hash_password, verify_password, 
    create_access_token, create_refresh_token, hash_token
)
from src.config import REFRESH_TOKEN_EXPIRE_DAYS

class AuthService:
    def register(self, username, email, password, fullname=None, phone=None, role=2, account_id=None, plan=0):
        if users_repo.find_by_username(username):
            raise ValueError("Username already exists")
        if users_repo.find_by_email(email):
            raise ValueError("Email already exists")
        if phone and users_repo.collection.find_one({"phone": phone}):
            raise ValueError("Số điện thoại đã tồn tại")
            
        # 1. Handle Account creation (Every new self-registered user gets an account)
        from src.repositories.accounts_repository import accounts_repo
        
        is_new_account = False
        if not account_id:
            account_data = {
                "plan": plan, # Use provided plan or default to 0 (free)
                "used_requests": 0,
                "created_at": datetime.utcnow()
            }
            account_id = accounts_repo.create(account_data)
            is_new_account = True
        
        try:
            # 2. Tạo user mới
            user = User(
                username=username,
                email=email,
                password=hash_password(password),
                fullname=fullname,
                phone=phone,
                role=role,
                account_id=account_id,
                auth_provider="local"
            )
            
            # 3. Lưu
            object_id = users_repo.create_user(user)
            return object_id, user.user_id
        except Exception as e:
            # Rollback: delete account if user creation failed and we created this account
            if is_new_account and account_id:
                try:
                    accounts_repo.delete(str(account_id))
                    Log.info(f"[Auth] Rollback: Deleted orphaned account {account_id} due to user register error")
                except Exception as rollback_err:
                    Log.error(f"[Auth] Rollback failed for account {account_id}: {rollback_err}")
            
            # Re-raise the original error (e.g. Unique index violation)
            if "duplicate key error" in str(e).lower():
                if "phone" in str(e).lower():
                    raise ValueError("Số điện thoại đã được đăng ký cho tài khoản khác")
                if "username" in str(e).lower():
                    raise ValueError("Username đã tồn tại")
                if "email" in str(e).lower():
                    raise ValueError("Email đã tồn tại")
            raise e

    def login(self, username, password, user_agent, ip, device_id=None, is_dev=False):
        # 1. Tìm user
        user_data = users_repo.find_by_username(username)
        if not user_data:
            raise ValueError("Invalid username or password")
            
        # 2. Verify Pass
        # Parse về Pydantic model để dễ truy cập field
        user = User(**user_data)
        if not user.password or not verify_password(password, user.password):
             raise ValueError("Invalid username or password")
        
        # 3. Check Device Lock - Will raise ValueError if failed
        if not is_dev:
            users_repo.check_device_id(str(user.id), device_id)

        # 4. Create Session & Tokens
        return self._create_login_response(user, user_agent, ip, device_id)

    def login_with_google(self, email, fullname, user_agent, ip, avatar_url=None, device_id=None):
        """
        Logins or registers a user via Google OAuth.
        """
        # 1. Tìm user theo email
        user_data = users_repo.find_by_email(email)
        
        if not user_data:
            # Create new user
            from src.utils.security import generate_user_api_key
            from src.models.user import UserApiKey
            
            full_key, access_key, hashed_secret, plain_secret = generate_user_api_key()
            
            api_key_model = UserApiKey(
                access_key=access_key,
                hashed_secret=hashed_secret,
                plain_secret=plain_secret,
                created_at=datetime.now()
            )

            user = User(
                email=email,
                fullname=fullname,
                avatar_url=avatar_url,
                auth_provider="google",
                active=True,
                api_key=api_key_model
            )
            # username is optional, maybe leave it empty or generate one?
            
            object_id = users_repo.create_user(user)
            # Populate ID back to user object for session creation
            user.id = object_id
        else:
            user = User(**user_data)
            
            # Optional: Update fullname/avatar if provided
            update_data = {}
            if not user.fullname and fullname:
                update_data["fullname"] = fullname
                user.fullname = fullname
            
            if avatar_url and user.avatar_url != avatar_url:
                update_data["avatar_url"] = avatar_url
                user.avatar_url = avatar_url
            
            if update_data:
                 users_repo.update(str(user.id), update_data)

        # 2. Check Device Lock - Will raise ValueError if failed
        users_repo.check_device_id(str(user.id), device_id)

        # 3. Return Tokens
        return self._create_login_response(user, user_agent, ip, device_id)

    def _create_login_response(self, user, user_agent, ip, device_id):
        # 1. Tạo Tokens
        access_token = create_access_token(str(user.id))
        refresh_token = create_refresh_token()
        
        # 2. Lưu Session
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
        
        # 3. Handle API Key
        # STRATEGY: Store plain secret in DB (Unsafe but requested) and always return full key.
        from src.utils.security import generate_user_api_key
        
        full_key_response = None
        
        # Check if user has a key AND has plain_secret stored
        if user.api_key and getattr(user.api_key, 'plain_secret', None):
            # REUSE EXISTING KEY (Persistent API Key)
            full_key_response = f"{user.api_key.access_key}.{user.api_key.plain_secret}"
        else:
            # Generate NEW key (if missing OR if old key didn't have plain_secret)
            full_key, access_key, hashed_secret, plain_secret = generate_user_api_key()
            
            # Save to DB with plain_secret
            users_repo.update(str(user.id), {
                "api_key": {
                    "access_key": access_key,
                    "hashed_secret": hashed_secret,
                    "plain_secret": plain_secret, # Saving Plaintext!
                    "created_at": datetime.now()
                }
            })
            full_key_response = full_key

        # 4. Get Account Info
        from src.services.subscription_service import subscription_service
        quota_data = None
        if user.account_id:
            quota_data = subscription_service.get_quota_info(user.account_id)

        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "api_key": full_key_response, # Always Full Key
            "user": {
                "id": str(user.id),
                "user_id": int(user.user_id) if user.user_id else None,
                "email": user.email,
                "fullname": user.fullname,
                "role": user.role,
                "account_id": str(user.account_id) if user.account_id else None,
                "avatar_url": getattr(user, "avatar_url", None),
                "group_key": getattr(user, "group_key", None),
                "quota": quota_data
            }
        }

    def reduce_refresh_token(self, old_refresh_token):
        """
        Refresh Token Rotation:
        - Validate old token
        - Revoke old token (session)
        - Create NEW session with NEW refresh token
        - Return both new Access & Refresh tokens
        """
        # 1. Hash token cũ
        old_hash = hash_token(old_refresh_token)
        
        # 2. Tìm session cũ
        session_data = auth_repo.find_by_hash(old_hash)
        if not session_data:
            # Có thể log warning security ở đây (Token Reuse Detection)
            raise ValueError("Invalid refresh token")
            
        session = AuthSession(**session_data)
        
        # 3. Validate
        if session.revoked:
             # Token Reuse Detected! Nên revoke toàn bộ session của user này để bảo mật
             # auth_repo.revoke_all_user_sessions(session.user_id)
             raise ValueError("Session revoked (Token reused?)")
             
        if session.expires_at < datetime.now():
            raise ValueError("Refresh token expired")
            
        # 4. Revoke token Cũ (Rotation)
        auth_repo.revoke_session(old_hash)
        
        # 5. Tạo Token Mới
        new_access_token = create_access_token(session.user_id)
        new_refresh_token = create_refresh_token()
        new_refresh_hash = hash_token(new_refresh_token)
        
        # Giữ nguyên thông tin thiết bị, chỉ update thời gian hết hạn mới
        new_expires_at = datetime.now() + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
        
        new_session = AuthSession(
            user_id=session.user_id,
            refresh_token_hash=new_refresh_hash,
            user_agent=session.user_agent,
            device_id=session.device_id,
            ip=session.ip,
            expires_at=new_expires_at
        )
        auth_repo.create_session(new_session)
        
        return {
            "access_token": new_access_token,
            "refresh_token": new_refresh_token
        }

    def logout(self, refresh_token):
        token_hash = hash_token(refresh_token)
        auth_repo.revoke_session(token_hash)

auth_service = AuthService()
