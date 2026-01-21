import re
import os
from src.utils.logger import Log
from src.config import CCCD_PROVINCE_CODE_MAP, DEFAULT_PLACE_OF_ISSUE, DEFAULT_NATIONALITY
from datetime import datetime

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
            clean_id = re.sub(r"[^0-9]", "", str(raw_id))
            cleaned_data["idNumber"] = clean_id
            
        # 2. Clean Date Fields (Chuẩn hóa DD/MM/YYYY)
        date_fields = ["dob", "expiryDate", "dateOfIssue", "dateOfBegining", "ngay_lap_phieu"]
        for field in date_fields:
            if field in cleaned_data and cleaned_data[field]:
                cleaned_data[field] = PostCleaner._format_date(str(cleaned_data[field]))

        # 3. Clean Name (Viết hoa chữ cái đầu mỗi từ, xóa ký tự đặc biệt)
        if "fullName" in cleaned_data and cleaned_data["fullName"]:
            cleaned_data["fullName"] = PostCleaner._format_name(str(cleaned_data["fullName"]))
            
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
                final_data[k] = cleaned_data.get(k, None)
            
            # Thêm các field khác nếu có (như debug info hoặc field lạ)
            for k, v in cleaned_data.items():
                if k not in ordered_keys:
                    final_data[k] = v
            
            return final_data

        return cleaned_data

    

    @staticmethod
    def extract_cccd_manual(raw_text):
        """
        Trích xuất dữ liệu CCCD thủ công từ chuỗi định dạng:|
        Số CCCD|Họ tên|Ngày sinh|Giới tính|Địa chỉ|Ngày cấp
        """
        if not raw_text: return None
        
        # Split by | and filter empty parts logic
        parts = [p.strip() for p in raw_text.split('|') if p.strip()]
        
        # Logic 0-5 mapping
        if len(parts) < 6:
            Log.warning(f"[PostCleaner] Manual CCCD extraction failed: Required 6 fields, got {len(parts)}")
            return None
            
        res = {
            "idNumber": parts[0],
            "fullName": parts[1],
            "dob": parts[2],
            "gender": parts[3],
            "address": parts[4],
            "dateOfIssue": parts[5],
        }

        # Quê quán từ 3 số đầu
        if len(res["idNumber"]) >= 3:
            province_code = res["idNumber"][:3]
            res["hometown"] = CCCD_PROVINCE_CODE_MAP.get(province_code, "Không xác định")
        
        # Tính ngày hết hạn
        expiry_date, expiry_type = PostCleaner.calculate_cccd_expiry(res["dob"], res["dateOfIssue"])
        res["expiryDate"] = expiry_date
        res["placeOfIssue"] = DEFAULT_PLACE_OF_ISSUE
        res["nationality"] = DEFAULT_NATIONALITY

        return PostCleaner.clean(res, doc_type="idCard")

    @staticmethod
    def extract_driver_manual(raw_text):
        """
        Trích xuất Giấy phép lái xe thủ công. 
        Ưu tiên tách dòng (Newline) hoặc dấu Pipe (|)
        Thứ tự: 0: Số | 1: Tên | 2: Ngày sinh | 3: Hạng | 4: Địa chỉ
        """
        if not raw_text: return None
        
        # Tách theo dòng hoặc dấu |
        if "|" in raw_text:
            parts = [p.strip() for p in raw_text.split('|') if p.strip()]
        else:
            parts = [p.strip() for p in raw_text.split('\n') if p.strip()]

        if len(parts) < 4:
            Log.warning(f"[PostCleaner] Manual DriverLicense failed: Required >=4 fields, got {len(parts)}")
            return None
            
        res = {
            "idNumber": parts[0],
            "fullName": parts[1],
            "dob": parts[2],
            "rank": parts[3],
            "address": parts[4] if len(parts) > 4 else None,
            "nationality": DEFAULT_NATIONALITY
        }
        
        return PostCleaner.clean(res, doc_type="driverLicense")

    @staticmethod
    def calculate_cccd_expiry(dob_str, issue_date_str):
        """
        Mốc tuổi: 14 -> 25 -> 40 -> 60
        Nếu cấp trong vòng 2 năm trước mốc -> nhảy mốc.
        >= 60 -> không thời hạn.
        """
        try:
            def parse_d(s):
                s = re.sub(r"[^0-9]", "", str(s))
                if len(s) == 8:
                    return datetime.strptime(s, "%d%m%Y")
                return None
            
            dob = parse_d(dob_str)
            issue_date = parse_d(issue_date_str)
            if not dob or not issue_date: return None, "Lỗi định dạng ngày"

            # Tuổi tại thời điểm cấp
            age = issue_date.year - dob.year - ((issue_date.month, issue_date.day) < (dob.month, dob.day))
            
            if age >= 58:
                return "Không thời hạn", "Cấp sau 58 tuổi"
            
            milestones = [25, 40, 60]
            target_age = None
            for m in milestones:
                if age < m:
                    target_age = m
                    break
            
            # Cấp trong vòng 2 năm trước mốc -> nhảy mốc
            if target_age and (target_age - age <= 2):
                idx = milestones.index(target_age)
                if idx + 1 < len(milestones):
                    target_age = milestones[idx+1]
                else:
                    return "Không thời hạn", f"Cấp trong vòng 2 năm trước {target_age}"

            if not target_age: return "Không thời hạn", "Đã qua các mốc"

            # Hết hạn vào sinh nhật tuổi target_age
            try:
                expiry = dob.replace(year=dob.year + target_age)
            except ValueError: # Handle Feb 29
                expiry = dob.replace(year=dob.year + target_age, day=28)
                
            return expiry.strftime("%d/%m/%Y"), f"Hết hạn ở tuổi {target_age}"
        except Exception as e:
            Log.error(f"[PostCleaner] Expiry error: {e}")
            return None, str(e)

    @staticmethod
    def _format_date(date_str):
        """
        Input: 01012000, 01-01-2000, 01/01/2000, 01.01.2000
        Output: 01/01/2000
        """
        # Nếu là chuỗi số thuần túy 8 ký tự
        s = re.sub(r"[^0-9]", "", date_str)
        if len(s) == 8:
            return f"{s[:2]}/{s[2:4]}/{s[4:]}"
            
        # Xóa ký tự lạ (chỉ giữ số và separator)
        date_str = re.sub(r"[^0-9\-\/\.]", "", date_str)
        # Thay thế separator thành /
        date_str = re.sub(r"[\-\.]", "/", date_str)
        return date_str

    @staticmethod
    def _format_name(name_str):
        name_str = re.sub(r"[;:\"'.,!@#$%^&*()+=]", "", name_str)
        return name_str.strip().title()
