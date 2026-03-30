"""
Text Cleaner
Làm sạch text sử dụng AI model
"""
import time
from datetime import datetime
from src.models.model_loader import model_loader
from src.config import DATE_KEYWORDS, FRONT_KEYWORDS, BACK_KEYWORDS, MENU_KEYWORDS 
from src.utils.logger import Log


def clean_text_basic(line):
    """
    Hàm clean text cơ bản (Bỏ AI model để tiết kiệm RAM)
    Làm sạch 1 dòng text duy nhất.
    """
    if not line or not line.strip():
        return ""
    
    # Chỉ trả về text đã trim, không dùng model AI nữa
    return line.strip()

from rapidfuzz import fuzz

def clean_text_lines(input_data):
    """
    Clean toàn bộ danh sách các dòng text nhưng CHỈ clean những dòng 
    có khả năng là Label (khớp với keywords).
    Input: list string OR list dict {'text': ..., 'box': ...}
    """
    start_time = time.time()
    
    # Pool all keywords to check against
    KEYWORDS_POOL = FRONT_KEYWORDS + BACK_KEYWORDS + DATE_KEYWORDS + MENU_KEYWORDS
    
    # Function to check if line needs cleaning
    def needs_cleaning(text):
        if not text or len(text) < 3: return False
        text_lower = text.lower()
        
        # Check fuzzy match with any keyword
        for kw in KEYWORDS_POOL:
            # Partial ratio is good for finding label inside noise
            score = fuzz.partial_ratio(text_lower, kw.lower())
            if score > 60: # Threshold: looks like a label
                return True
        return False

    Log.info(f"[CLEAN] 🧹 Bắt đầu Selective Clean {len(input_data)} dòng...")
    
    cleaned_results = []
    clean_count = 0
    
    # Detect input type
    is_legacy = False
    if len(input_data) > 0 and isinstance(input_data[0], str):
        is_legacy = True
        
    for item in input_data:
        original_text = item if is_legacy else item.get("text", "")
        
        # Decision: Clean or Keep?
        if needs_cleaning(original_text):
            cleaned_text = clean_text_basic(original_text)
            clean_count += 1
            if cleaned_text != original_text:
                Log.info(f"   [CLEAN] 🔄 Đã sửa: '{original_text}' => '{cleaned_text}'")
            else:
                Log.info(f"   [CLEAN] ➖ Giữ nguyên: '{original_text}'")
        else:
            cleaned_text = original_text.strip()
            
        if is_legacy:
            cleaned_results.append(cleaned_text)
        else:
            # Create new item with cleaned text, preserving box
            new_item = item.copy()
            new_item["text"] = cleaned_text
            cleaned_results.append(new_item)
        
    elapsed = time.time() - start_time
    Log.info(f"[CLEAN] ✅ Clean xong. Đã sửa {clean_count}/{len(input_data)} dòng (Label) trong {elapsed:.2f}s")
    return cleaned_results
