import re
from app.utils.logger import Log

class PostCleaner:
    """
    Hậu xử lý data sau khi extract
    Mục đích: Chuẩn hóa format (ngày tháng, số), loại bỏ rác OCR lần cuối.
    """
    
    @staticmethod
    def clean(data, doc_type="idCard"):
        if not data: return {}
        
        cleaned_data = data.copy()
        
        # 1. Clean ID Number (Xóa khoảng trắng, ký tự lại)
        if "idNumber" in cleaned_data and cleaned_data["idNumber"]:
            raw_id = cleaned_data["idNumber"]
            # Chỉ giữ lại số
            clean_id = re.sub(r"[^0-9]", "", raw_id)
            cleaned_data["idNumber"] = clean_id
            
        # 2. Clean Date Fields (Chuẩn hóa DD/MM/YYYY)
        date_fields = ["dob", "expiryDate", "dateOfIssue", "dateOfBegining", "ngay_lap_phieu"]
        for field in date_fields:
            if field in cleaned_data and cleaned_data[field]:
                cleaned_data[field] = PostCleaner._format_date(cleaned_data[field])

        # 3. Clean Name (Viết hoa chữ cái đầu mỗi từ, xóa ký tự đặc biệt)
        if "fullName" in cleaned_data and cleaned_data["fullName"]:
            cleaned_data["fullName"] = PostCleaner._format_name(cleaned_data["fullName"])
            
        # 4. Reorder Keys (Quan trọng để JSON đẹp và đúng thứ tự Schema)
        
        # Định nghĩa thứ tự cho từng loại
        key_orders = {
            "idCard": [
                "idNumber", "fullName", "dob", "gender", "nationality", 
                "hometown", "address", "expiryDate", "dateOfIssue", "placeOfIssue"
            ],
            "driverLicense": [
                "idNumber", "fullName", "dob", "rank","nationality", "address", 
                "expiryDate", "dateOfIssue", "dateOfBegining", "placeOfIssue"
            ],
            "invoice": [
                "so_hoa_don", "ngay_lap_phieu", "tong_so_tien", "noi_dung_hoa_don"
            ],
            "document": [
                "title", "summary", "keywords", "dates", "entities"
            ]
        }
        
        ordered_keys = key_orders.get(doc_type)
        
        if ordered_keys:
            # Tạo dict mới theo thứ tự
            final_data = {}
            for k in ordered_keys:
                final_data[k] = cleaned_data.get(k, "")
            
            # Thêm các field khác nếu có (như debug info hoặc field lạ)
            for k, v in cleaned_data.items():
                if k not in ordered_keys:
                    final_data[k] = v
            
            return final_data

        return cleaned_data

    @staticmethod
    def _format_date(date_str):
        """
        Input: 01-01-2000, 01/01/2000, 01.01.2000
        Output: 01/01/2000
        """
        # Xóa ký tự lạ (chỉ giữ số và separator)
        date_str = re.sub(r"[^0-9\-\/\.]", "", date_str)
        # Thay thế separator thành /
        date_str = re.sub(r"[\-\.]", "/", date_str)
        return date_str

    @staticmethod
    def _format_name(name_str):
        # Xóa ký tự đặc biệt không phải chữ
        # (Giữ lại tiếng Việt có dấu)
        # Cách đơn giản: Xóa các ký tự ; : " ' ...
        name_str = re.sub(r"[;:\"'.,!@#$%^&*()+=]", "", name_str)
        return name_str.strip().title() # Viết hoa chữ cái đầu
