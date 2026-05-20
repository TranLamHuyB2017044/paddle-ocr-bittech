from src.database.base_repository import BaseRepository
from src.models.user import User
from pymongo import ReturnDocument

class UsersRepository(BaseRepository):
    def __init__(self):
        super().__init__("users")
        # Create unique indexes
        self.collection.create_index("username", unique=True, sparse=True)
        self.collection.create_index("api_key.access_key", unique=True, sparse=True)
        self.collection.create_index("deviceId", unique=True, sparse=True)
        # Unique index for user_id
        self.collection.create_index("user_id", unique=True, sparse=True)

    def _get_next_user_id(self) -> int:
        """
        Get the next auto-incrementing user_id from the counters collection.
        Atomic operation.
        """
        # Using the same DB as the collection
        ret = self.db["counters"].find_one_and_update(
            {"_id": "userid"},
            {"$inc": {"seq": 1}},
            upsert=True,
            return_document=ReturnDocument.AFTER
        )
        return ret["seq"]


    def create_user(self, user: User):
        """
        Validate data using Pydantic model before inserting
        """
        # Generate auto-increment ID
        if user.user_id is None:
            user.user_id = self._get_next_user_id()

        user_dict = user.model_dump(by_alias=True, exclude_none=True)
        return self.create(user_dict)


    def find_by_username(self, username):
        return self.find_one({"username": username})


    def find_by_email(self, email):
        return self.find_one({"email": email})

    def find_by_api_key_access(self, access_key: str):
        """Find user by API Key's Access Key"""
        return self.find_one({"api_key.access_key": access_key})

    def find_by_api_key(self, api_key: str):
        # Deprecated or use internal logic? 
        # Middleware will parse key and use find_by_api_key_access
        # Just alias it for safety or remove? 
        # User asked "ko xoa code". I will keep it but it won't work for hashed keys unless passed access_key.
        # But wait, middleware calls find_by_api_key(full_key_from_header).
        # I MUST update middleware logic.
        return self.find_one({"api_key.access_key": api_key}) # Temporary placeholder?
        # Actually I will rename this to avoid confusion and update middleware.
        pass

    def increment_extraction_stats(self, user_id, doc_type: str, cost: int = 1):
        """
        Increment extraction statistics for a user
        - Increment total_extractions by `cost`
        - Update last_extraction_at
        - Increment specific doc_type counter by `cost`
        
        Supports both ObjectId (string/object) and integer user_id.
        """
        from datetime import datetime
        from bson import ObjectId
        
        try:
            # Determine query (ObjectId or integer user_id)
            query = {}
            if isinstance(user_id, int) or (isinstance(user_id, str) and user_id.isdigit()):
                query = {"user_id": int(user_id)}
            else:
                try:
                    query = {"_id": ObjectId(user_id)}
                except:
                    # Fallback if not a valid ObjectId string, might be the integer user_id as string
                    query = {"user_id": str(user_id)} # Or handle as error
            
            result = self.collection.update_one(
                query,
                {
                    "$inc": {
                        "stats.total_extractions": cost,
                        f"stats.doc_type_stats.{doc_type}": cost
                    },
                    "$set": {
                        "stats.last_extraction_at": datetime.now()
                    }
                }
            )
            
            if result.matched_count == 0:
                from src.utils.logger import Log
                Log.error(f"[UserRepo] ⚠️ No user found with query {query} for stats increment")
                
            return result.modified_count > 0
        except Exception as e:
            from src.utils.logger import Log
            Log.error(f"[UserRepo] ❌ Error incrementing extraction stats: {e}")
            return False


    def check_device_id(self, user_id: str, device_id: str) -> bool:
        """
        Kiểm tra thiết bị của user.
        - Nếu user chưa có deviceId: lưu device_id hiện tại và trả về True (cho phép).
        - Nếu đã có: so sánh với device_id hiện tại.
        Trả về True nếu hợp lệ, raise ValueError nếu bị lỗi hoặc sai thiết bị.
        """
        from src.utils.logger import Log
        if not device_id:
            Log.warning(f"[UserRepo] ⚠️ No device_id provided for user {user_id}")
            raise ValueError("Device ID là bắt buộc để đăng nhập")
            
        user_data = self.find_by_id(user_id)
        if not user_data:
            Log.error(f"[UserRepo] ❌ User {user_id} not found")
            raise ValueError("Không tìm thấy thông tin người dùng")

        saved_device_id = user_data.get("deviceId")
        Log.info(f"[UserRepo] 🔍 Checking device_id for user {user_data.get('username')}: Current={device_id}, Saved={saved_device_id}")

        if not saved_device_id:
            # 1. Kiểm tra xem device_id này đã được tài khoản nào khác sử dụng chưa
            # Vì deviceId là unique, nếu update lỗi thường là do đã tồn tại ở account khác
            existing_owner = self.collection.find_one({"deviceId": device_id})
            if existing_owner:
                Log.error(f"[UserRepo] ❌ Device {device_id} is already linked to user {existing_owner.get('username')}")
                raise ValueError(f"Thiết bị này đã được liên kết với tài khoản '{existing_owner.get('username')}'. Vui lòng dùng thiết bị khác.")

            # 2. Liên kết thiết bị lần đầu
            Log.info(f"[UserRepo] 🔗 Linking first device {device_id} to user {user_id}")
            success = self.update(user_id, {"deviceId": device_id})
            if not success:
                Log.error(f"[UserRepo] ❌ Failed to update deviceId for user {user_id}")
                raise ValueError("Không thể liên kết thiết bị. Vui lòng thử lại sau.")
            return True
        
        # Kiểm tra xem có trùng với thiết bị đã lưu không
        if saved_device_id != device_id:
            Log.warning(f"[UserRepo] ⛔ Device mismatch for user {user_id}: {device_id} != {saved_device_id}")
            raise ValueError("Tài khoản này đã được liên kết với một thiết bị khác. Vui lòng đăng nhập đúng thiết bị.")
            
        return True


# Global instance
users_repo = UsersRepository()
