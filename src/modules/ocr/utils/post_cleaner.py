import re
import os
import time
from src.shared.utils.logger import Log
from src.core.config import CCCD_PROVINCE_CODE_MAP, DEFAULT_PLACE_OF_ISSUE, DEFAULT_NATIONALITY
from datetime import datetime 

class PostCleaner:
    """
    Hậu xử lý data sau khi extract
    Mục đích: Chuẩn hóa format (ngày tháng, số), loại bỏ rác OCR lần cuối.
    """
    
    # Local Cache to store common corrections and avoid DB calls on every request
    _corrections_cache = {}
    _last_cache_update = 0.0
    CACHE_TTL = 300  # 5 minutes

    @staticmethod
    def _load_corrections(doc_type):
        """
        Load common corrections from DB into a fast lookup structure.
        Structure: { field_name: { raw_text_lower: corrected_text } }
        """
        now = time.time()
        cache_key = f"rules_{doc_type}"
        
        # Return from cache if valid
        if cache_key in PostCleaner._corrections_cache and (now - PostCleaner._last_cache_update < PostCleaner.CACHE_TTL):
            return PostCleaner._corrections_cache[cache_key]

        try:
            from src.modules.ocr.repositories.corrections_repository import corrections_repo
            rules = corrections_repo.get_common_corrections(doc_type, min_count=2)
            
            # Organize for O(1) field-based lookup
            organized_rules = {}
            for r in rules:
                f_name = r["field_name"]
                if f_name not in organized_rules:
                    organized_rules[f_name] = []
                organized_rules[f_name].append({
                    "raw": str(r["raw_text"]).lower().strip(),
                    "fixed": r["corrected_text"]
                })
            
            PostCleaner._corrections_cache[cache_key] = organized_rules
            PostCleaner._last_cache_update = now
            return organized_rules
        except Exception as e:
            Log.error(f"[PostCleaner] Cache load error: {e}")
            return {}

    @staticmethod
    def normalize_price(price_str):
        """
        Chuyển đổi các định dạng giá như 50k, 1.2tr, 50.000đ thành số nguyên (dưới dạng chuỗi)
        """
        if not price_str or not isinstance(price_str, str):
            return price_str
            
        original = price_str.lower().strip()
        # Loại bỏ các ký tự không phải số và đơn vị (k, tr, đ, dot, comma)
        # Giữ lại số và các chữ k, t, r
        import re
        
        # Xử lý trường hợp "k" (nghìn)
        if 'k' in original:
            val = re.findall(r"[\d.]+", original)
            if val:
                try:
                    return str(int(float(val[0].replace(',', '')) * 1000))
                except: pass
                
        # Xử lý trường hợp "tr" hoặc "triệu"
        if 'tr' in original or 'triệu' in original:
            val = re.findall(r"[\d.]+", original)
            if val:
                try:
                    return str(int(float(val[0].replace(',', '')) * 1000000))
                except: pass
        
        # Trường hợp bình thường: xóa các ký tự không phải số
        numeric_only = re.sub(r"[^\d]", "", original)
        return numeric_only if numeric_only else price_str

    @staticmethod
    def _normalize_address_part(text):
        """
        Chuẩn hóa phần Tỉnh/Thành phố trong địa chỉ bằng Fuzzy Matching.
        Giúp tránh Hallucination bằng cách ép về danh mục thực tế.
        """
        if not text or len(str(text)) < 3:
            return text
            
        from rapidfuzz import process, fuzz
        from src.core.config import CCCD_PROVINCE_CODE_MAP
        
        provinces = list(set(CCCD_PROVINCE_CODE_MAP.values()))
        
        # Tách text thành các phần (thường Tỉnh/Thành phố ở cuối)
        parts = [p.strip() for p in str(text).split(',')]
        if not parts:
            return text
            
        last_part = parts[-1]
        
        # Tìm kiếm mờ trong danh sách tỉnh
        match = process.extractOne(last_part, provinces, scorer=fuzz.token_sort_ratio)
        
        if match and match[1] >= 85:
            # Nếu tìm thấy Tỉnh khớp > 85%, thay thế phần cuối bằng Tỉnh chuẩn
            parts[-1] = match[0]
            return ", ".join(parts)
            
        return text

    @staticmethod
    def clean(data, doc_type="idCard"):
        if not data: return {}
        
        cleaned_data = data.copy()

        # 0. Normalize Address/Hometown (New Logic)
        for field in ["address", "hometown"]:
            if field in cleaned_data and cleaned_data[field]:
                cleaned_data[field] = PostCleaner._normalize_address_part(cleaned_data[field])

        # 1. Clean ID Number (Xóa khoảng trắng, ký tự lại, Regex semantic CCCD/CMND/GPLX)
        if "idNumber" in cleaned_data and cleaned_data["idNumber"]:
            raw_id = str(cleaned_data["idNumber"]).replace(" ", "")
            
            if doc_type == "idCard":
                # Quy tắc ngầm CCCD 12 số:
                # - 3 số đầu: Mã tỉnh (001 đến 096)
                # - 1 số kế: Thế kỷ & Giới tính (0-9)
                # - 2 số kế: Năm sinh (00-99)
                # - 6 số cuối: Ngẫu nhiên
                # Regex CCCD chuẩn: (Mã tỉnh 001-096)(Thế kỷ 0-5)(Năm sinh 2 số)(Ngẫu nhiên 6 số) -> (0[0-8][0-9]|09[0-6])[0-5]\d{8}
                # CMND cũ: 9 số bất kỳ
                cccd_pattern = r"(?<!\d)((0[0-8][0-9]|09[0-6])[0-5]\d{8}|\d{9})(?!\d)"
                match = re.search(cccd_pattern, raw_id)
                if match:
                    clean_id = match.group(1)
                else:
                    # Fallback bóc tách 12 số (chấp nhận rủi ro sai OCR ở mã tỉnh/thế kỷ) hoặc 9 số
                    clean_id = re.sub(r"[^0-9]", "", raw_id)
                    match_fallback = re.search(r"(\d{12}|\d{9})", clean_id)
                    if match_fallback:
                        clean_id = match_fallback.group(1)
            elif doc_type == "driverLicense":
                # GPLX luôn có 12 số
                match = re.search(r"(?<!\d)(\d{12})(?!\d)", raw_id)
                if match:
                    clean_id = match.group(1)
                else:
                    clean_id = re.sub(r"[^0-9]", "", raw_id)
                    match_fallback = re.search(r"(\d{12})", clean_id)
                    if match_fallback:
                        clean_id = match_fallback.group(1)
            else:
                clean_id = re.sub(r"[^0-9]", "", raw_id)
                
            cleaned_data["idNumber"] = clean_id
            
        # 2. Clean Date Fields (Chuẩn hóa DD/MM/YYYY)
        date_fields = ["dob", "expiryDate", "dateOfIssue", "dateOfBegining", "ngay_lap_phieu"]
        for field in date_fields:
            if field in cleaned_data and cleaned_data[field]:
                cleaned_data[field] = PostCleaner._format_date(str(cleaned_data[field]))

        # 3. Clean Name (Viết hoa chữ cái đầu mỗi từ, xóa ký tự đặc biệt)
        if "fullName" in cleaned_data and cleaned_data["fullName"]:
            cleaned_data["fullName"] = PostCleaner._format_name(str(cleaned_data["fullName"]))

        # --- NEW: Học từ Correction Dictionary (Áp dụng cho mọi loại tài liệu) ---
        try:
            from rapidfuzz import fuzz
            # LOAD TỪ CACHE (Tốn O(1) để lấy rules đã tổ chức sẵn)
            organized_rules = PostCleaner._load_corrections(doc_type)
            
            if organized_rules:
                # Chỉ kiểm tra các quy tắc cho những field THỰC SỰ có trong data hiện tại
                for field_name, value in cleaned_data.items():
                    if field_name in organized_rules:
                        current_v = str(value).lower().strip()
                        
                        # Duyệt qua các quy tắc của RIÊNG field này
                        for rule in organized_rules[field_name]:
                            old_v = rule["raw"]
                            new_v = rule["fixed"]
                            
                            # So sánh mờ (Fuzzy)
                            if fuzz.ratio(current_v, old_v) >= 90:
                                if value != new_v:
                                    Log.info(f"[PostCleaner] 🎓 Optimized Fuzzy Learning: '{value}' ≈ '{old_v}' -> '{new_v}'")
                                    cleaned_data[field_name] = new_v
                                    break # Đã sửa xong field này, không cần check rule khác
        except Exception as e:
            Log.error(f"[PostCleaner] Learning optimization error: {e}")

        # 4. Clean Price/Amount for Menu and Invoice
        if doc_type == "menu" and "menu_items" in cleaned_data:
            items = cleaned_data["menu_items"]
            if isinstance(items, list):
                for item in items:
                    if "price" in item and item["price"]:
                        item["price"] = PostCleaner.normalize_price(item["price"])
        
        if doc_type == "invoice":
            price_fields = ["tong_so_tien", "total_amount", "tong_tien"]
            for f in price_fields:
                if f in cleaned_data and cleaned_data[f]:
                    cleaned_data[f] = PostCleaner.normalize_price(cleaned_data[f])
            
            # Normalize and Fix common typos for Invoice titles
            if "ten_hoa_don" in cleaned_data and cleaned_data["ten_hoa_don"]:
                title = str(cleaned_data["ten_hoa_don"]).lower()
                
                # Dictionary of common typos and their corrections
                corrections = {
                    "hóa đơn bán lê": "Hóa đơn bán lẻ",
                    "hoa don ban le": "Hóa đơn bán lẻ",
                    "hđ bán lẻ": "Hóa đơn bán lẻ",
                    "hđ gtgt": "Hóa đơn GTGT",
                    "hóa đơn gtgt": "Hóa đơn GTGT",
                    "hđ bán hàng": "Hóa đơn bán hàng",
                    "phiếu tính tiền": "Phiếu thanh toán",
                    "biên lai": "Biên lai",
                    "phiếu thu": "Phiếu thu"
                }
                
                for typo, fixed in corrections.items():
                    if typo in title:
                        cleaned_data["ten_hoa_don"] = fixed
                        break
             
        # 5. Reorder Keys (Quan trọng để JSON đẹp và đúng thứ tự Schema)
        
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
            ],
            "menu": [
                "business_name", "business_info", "menu_items"
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
        
        # Nếu index thứ 1 (phần tử thứ 2) không phải là text (không chứa chữ cái, ví dụ là số CCCD bị lệch)
        # thì bỏ qua phần tử thứ 2 và lấy vị trí tiếp theo làm index thứ 1.
        while len(parts) > 2 and not any(c.isalpha() for c in parts[1]):
            parts.pop(1)

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
        Input: 01012000, 01-01-2000, 01/01/2000, 01.01.2000, 2026-06-08
        Output: 01/01/2000
        """
        # Nếu là chuỗi số thuần túy 8 ký tự
        s = re.sub(r"[^0-9]", "", date_str)
        if len(s) == 8:
            try:
                # Kiểm tra xem có bắt đầu bằng năm không (YYYYMMDD)
                year_start = int(s[:4])
                if 1900 <= year_start <= 2100:
                    return f"{s[6:]}/{s[4:6]}/{s[:4]}"
            except ValueError:
                pass
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
