from datetime import datetime
from src.database.base_repository import BaseRepository
from bson import ObjectId
from src.utils.logger import Log

class CorrectionsRepository(BaseRepository):
    def __init__(self):
        super().__init__("corrections")
    
    def log_correction(self, doc_type, field_name, original_text, corrected_text, user_id=None):
        """
        Lưu vết cặp chỉnh sửa từ người dùng.
        Nếu cặp này đã tồn tại, tăng count lên.
        """
        if not original_text or not corrected_text or original_text == corrected_text:
            return
            
        # Chuẩn hóa để tránh so sánh lệch
        raw = str(original_text).strip()
        fixed = str(corrected_text).strip()
        
        # Tìm xem đã có cặp này chưa theo cùng loại tài liệu và field
        existing = self.collection.find_one({
            "doc_type": doc_type,
            "field_name": field_name,
            "raw_text": raw,
            "corrected_text": fixed
        })
        
        if existing:
            # Tăng count và cập nhật thời gian
            self.collection.update_one(
                {"_id": existing["_id"]},
                {
                    "$inc": {"occurrence_count": 1},
                    "$set": {"updated_at": datetime.now()}
                }
            )
        else:
            # Tạo mới
            data = {
                "doc_type": doc_type,
                "field_name": field_name,
                "raw_text": raw,
                "corrected_text": fixed,
                "occurrence_count": 1,
                "created_at": datetime.now(),
                "updated_at": datetime.now(),
                "user_id": ObjectId(user_id) if user_id else None
            }
            self.create(data)
            Log.info(f"[Learning] 🎓 New correction learned: '{raw}' -> '{fixed}' for field '{field_name}'")

    def get_common_corrections(self, doc_type, min_count=2):
        """
        Lấy các cặp chỉnh sửa phổ biến (được sửa nhiều lần) để áp dụng tự động.
        """
        cursor = self.collection.find({
            "doc_type": doc_type,
            "occurrence_count": {"$gte": min_count}
        }).sort("occurrence_count", -1)
        
        return list(cursor)

# Global instance
corrections_repo = CorrectionsRepository()
