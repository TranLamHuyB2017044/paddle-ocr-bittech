import re
import unicodedata
from src.utils.logger import Log

def normalize_vnum_text(text: str) -> str:
    """
    Normalize Vietnamese text to Unicode NFC form.
    """
    if not text:
        return ""
    return unicodedata.normalize('NFC', text)

def normalize_amounts(text: str) -> str:
    """
    Normalize amount formats to "XXXX VND".
    Example: 15.000.000đ or 15,000,000 VND -> 15000000 VND
    """
    if not text:
        return ""
    
    # 1. Tìm các chuỗi có vẻ là số tiền: 
    # - Có thể có dấu phân cách . hoặc ,
    # - Có hậu tố đ, VND, VNĐ, ...
    # Regex này tìm các cụm số có dấu phân cách theo sau là đơn vị tiền tệ
    # Ví dụ: 15.000.000, 15,000,000, 15000000
    
    # Một cách tiếp cận đơn giản hơn: Tìm các cụm số và đơn vị liên quan
    # Ví dụ: "Tổng tiền: 15.500.000 vnđ"
    
    # Pattern cho số tiền (ví dụ: 15.000.000 hoặc 15,000,000)
    # Hỗ trợ cả trường hợp có phần thập phân nếu cần, nhưng thường tiền Việt không dùng phần thập phân
    amount_pattern = r'(\d{1,3}(?:[.,]\d{3})*|\d+)\s*(?:đ|VND|VNĐ|vnd|vnđ)'
    
    def replacer(match):
        num_str = match.group(1)
        # Loại bỏ dấu phân cách . hoặc ,
        clean_num = num_str.replace('.', '').replace(',', '')
        return f"{clean_num} VND"

    try:
        normalized = re.sub(amount_pattern, replacer, text, flags=re.IGNORECASE)
        return normalized
    except Exception as e:
        Log.error(f"[NORMALIZER] Error normalizing amounts: {e}")
        return text

def normalize_document_text(text: str) -> str:
    """
    Full normalization for document text.
    """
    text = normalize_vnum_text(text)
    text = normalize_amounts(text)
    return text
