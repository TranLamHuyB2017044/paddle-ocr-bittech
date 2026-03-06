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
    Hàm clean text cơ bản sử dụng model AI
    Làm sạch 1 dòng text duy nhất.
    """
    if not line or not line.strip():
        return ""

    inputs = model_loader.tokenizer(
        line, 
        return_tensors="pt",
        truncation=True, 
        max_length=50 # Increased slightly for safety
    ).to(model_loader.device)

    outputs = model_loader.model.generate(
        **inputs,
        max_new_tokens=50,
        num_beams=3,
        num_return_sequences=1,
        early_stopping=True,
        do_sample=False,
        length_penalty=1.0
    )

    cleaned_line = model_loader.tokenizer.decode(outputs[0], skip_special_tokens=True)
    return cleaned_line

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
