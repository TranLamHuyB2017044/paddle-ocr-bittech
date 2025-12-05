"""
Front Extractor
Trích xuất thông tin từ mặt trước CCCD
"""
import re
from cccd.config import (
    DEFAULT_NATIONALITY,
    ADDRESS_KEYWORDS,
    EXPIRY_LABEL_KEYWORDS,
    HOMETOWN_KEYWORDS
)


def clean_label(text):
    """
    Làm sạch label (xóa dấu :, -, . ở cuối)
    
    Args:
        text: Text cần làm sạch
        
    Returns:
        str: Text đã được làm sạch
    """
    return re.sub(r"[:\-\.]*$", "", text.strip().lower())


def extract_front(texts):
    """
    Trích xuất thông tin từ mặt trước CCCD
    
    Args:
        texts: Danh sách các dòng text đã được làm sạch
        
    Returns:
        dict: Thông tin đã trích xuất
    """
    info = {
        "idNumber": "",
        "fullName": "",
        "dob": "",
        "gender": "",
        "nationality": DEFAULT_NATIONALITY,
        "hometown": "",
        "address": "",
        "expiryDate": "",
    }

    # Join full text
    full = " ".join(texts).lower()

    # ==========================
    # 1. CCCD: 9 hoặc 12 số
    # ==========================
    m = re.search(r"\b(\d{9}|\d{12})\b", full)
    if m:
        info["idNumber"] = m.group()

    # ==========================
    # 2. HỌ TÊN: Xử lý 3 trường hợp
    # ==========================
    # Regex để validate tên (ALL CAPS, có chữ cái tiếng Việt)
    name_regex = re.compile(r"^(?=.*[A-ZÀ-ỸĐ])[A-ZÀ-ỸĐ\s]{3,}$")
    
    # CHIẾN LƯỢC 1: Tìm label "Họ và tên" → lấy dòng TIẾP THEO
    for i, t in enumerate(texts):
        t_lower = t.lower().strip()
        # Kiểm tra xem có phải dòng label không
        if t_lower in ["họ và tên", "ho va ten", "họ tên", "ho ten", "full name", "name"]:
            # Lấy dòng tiếp theo (nếu có)
            if i + 1 < len(texts):
                next_line = texts[i + 1].strip()
                # Validate: Phải là ALL CAPS và có ít nhất 3 ký tự
                if name_regex.match(next_line):
                    info["fullName"] = next_line
                    print(f"[EXTRACT] ✅ Họ tên (label + next line): '{next_line}'")
                    break
    
    # CHIẾN LƯỢC 2: Tìm dòng chứa "Họ và tên: NGUYỄN VĂN A" (cùng dòng)
    if not info["fullName"]:
        for t in texts:
            if any(k in t.lower() for k in ["họ và tên", "họ tên", "ho ten", "ho va ten"]):
                # Xóa label, lấy phần còn lại
                cleaned = re.sub(r"(họ và tên|họ tên|ho va ten|ho ten)[:\-\s]*", "", t, flags=re.I)
                cleaned = cleaned.strip()
                # Validate: Phải là ALL CAPS
                if cleaned and name_regex.match(cleaned):
                    info["fullName"] = cleaned
                    print(f"[EXTRACT] ✅ Họ tên (same line): '{cleaned}'")
                    break
    
    # CHIẾN LƯỢC 3: Tìm dòng ALL CAPS (fallback - ưu tiên dòng dài)
    if not info["fullName"]:
        candidates = []
        for t in texts:
            t_stripped = t.strip()
            if name_regex.match(t_stripped):
                # Loại trừ các dòng không phải tên
                if not any(exclude in t_stripped.upper() for exclude in [
                    "CỘNG HÒA", "SOCIALIST", "VIỆT NAM", "VIET NAM",
                    "CĂN CƯỚC", "CHỨNG MINH", "CCCD", "CMND"
                ]):
                    candidates.append(t_stripped)
        
        # Chọn dòng dài nhất (thường là tên đầy đủ)
        if candidates:
            info["fullName"] = max(candidates, key=len)
            print(f"[EXTRACT] ✅ Họ tên (ALL CAPS fallback): '{info['fullName']}'")

    # ==========================
    # 3. Ngày sinh (DOB)
    # ==========================
    dob_regex = re.compile(
        r"(?i)(?:ngày\s*sinh|date\s*of\s*birth|birth)[:\s]*"
        r"(\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4})"
    )

    # Regex chỉ bắt ngày (dùng cho dòng phía dưới)
    date_only_regex = re.compile(r"\b(\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4})\b")

    for i, t in enumerate(texts):
        mm = dob_regex.search(t)
        if mm:
            # Trường hợp ngày nằm chung 1 dòng
            if mm.group(1):
                info["dob"] = mm.group(1)
                break

        # Trường hợp ngày NẰM Ở DÒNG PHÍA DƯỚI
        if i + 1 < len(texts):
            mm2 = date_only_regex.search(texts[i + 1])
            if mm2:
                info["dob"] = mm2.group(1)
                break

    # Nếu vẫn chưa có dob -> fallback (tự động quét toàn bộ)
    if not info["dob"]:
        for t in texts:
            mm = date_only_regex.search(t)
            if mm:
                info["dob"] = mm.group(1)
                break

    # ==========================
    # 4. Giới tính
    # ==========================
    if "nam" in full:
        info["gender"] = "Nam"
    else:
        info["gender"] = "Nữ"

    # ==========================
    # 5. Quê quán (hometown)
    # ==========================
    # Strategy 1: Label on one line → value next line
    for i, t in enumerate(texts):
        t_clean = clean_label(t)
        if any(k in t_clean for k in HOMETOWN_KEYWORDS):
            if i + 1 < len(texts):
                candidate = texts[i + 1].strip()
                if len(candidate) > 3:  # minimal content validation
                    info["hometown"] = candidate
                    print(f"[EXTRACT] ✅ Hometown (next line): {candidate}")
                    break

    # Strategy 2: Same line (e.g. 'Quê quán: Nam Định')
    if not info["hometown"]:
        for t in texts:
            t_lower = clean_label(t)
            for k in HOMETOWN_KEYWORDS:
                if k in t_lower:
                    # Remove label part
                    cleaned = re.sub(rf"{k}\s*[:\-]*\s*", "", t, flags=re.I).strip()
                    if len(cleaned) > 3:
                        info["hometown"] = cleaned
                        print(f"[EXTRACT] ✅ Hometown (same line): {cleaned}")
                        break
            if info["hometown"]:
                break

    # Strategy 3: Fallback – tìm dòng bắt đầu bằng 'Quê ...' nhưng OCR lỗi dấu
    if not info["hometown"]:
        for t in texts:
            t_l = t.lower()
            if t_l.startswith("que ") or t_l.startswith("quequan") or "que quan" in t_l:
                info["hometown"] = t.split(":")[-1].strip()
                print(f"[EXTRACT] 🟡 Hometown (fallback guess): {info['hometown']}")
                break

    # ==========================
    # 6. ĐỊA CHỈ 2 DÒNG (CHUẨN)
    # ==========================
    info["address"] = ""
    info["expiryDate"] = ""

    # --------------------------------------------------
    # 1) Tìm địa chỉ dòng 1 (sau dấu ":" nếu có)
    # --------------------------------------------------
    address_line_1 = ""
    address_index = -1

    for i, t in enumerate(texts):
        t_lower = t.lower()

        if any(k in t_lower for k in ADDRESS_KEYWORDS):
            address_index = i

            # lấy phần sau ':' nếu có
            if ":" in t:
                address_line_1 = t.split(":", 1)[1].strip()
            else:
                # không có ':' thì dùng luôn dòng này
                address_line_1 = t.strip()

            break

    # --------------------------------------------------
    # 2) Tìm ngày hết hạn (expiry) — ngay sau dòng "có giá trị đến"
    # --------------------------------------------------
    expiry_label_index = -1

    for i, t in enumerate(texts):
        t_lower = t.lower()

        if any(k in t_lower for k in EXPIRY_LABEL_KEYWORDS):
            expiry_label_index = i

            # dòng sau là ngày hết hạn
            if i + 1 < len(texts):
                info["expiryDate"] = texts[i + 1].strip()

            break

    # --------------------------------------------------
    # 3) Địa chỉ dòng 2 = dòng sau "Date of expiry"
    # --------------------------------------------------
    address_line_2 = ""

    for i, t in enumerate(texts):
        if "date of expiry" in t.lower():
            if i + 1 < len(texts):
                address_line_2 = texts[i + 1].strip()
            break

    # --------------------------------------------------
    # 4) Gộp địa chỉ (line1 + line2)
    # --------------------------------------------------
    if address_line_1 and address_line_2:
        info["address"] = f"{address_line_1}, {address_line_2}"
    else:
        info["address"] = address_line_1 or address_line_2

    return info
