"""
Text Cleaner
Làm sạch text sử dụng AI model
"""
import time
from datetime import datetime
from app.models.model_loader import model_loader
from app.config import DATE_KEYWORDS, FRONT_KEYWORDS
from app.utils.logger import Log


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

def clean_text_lines(lines):
    """
    Clean toàn bộ danh sách các dòng text
    Không phân biệt mặt trước/sau hay loại giấy tờ.
    """
    start_time = time.time()
    Log.info(f"[CLEAN] 🧹 Bắt đầu clean {len(lines)} dòng...")
    
    cleaned_lines = []
    for i, line in enumerate(lines):
        cl = clean_text_basic(line)
        cleaned_lines.append(cl)
        
    elapsed = time.time() - start_time
    Log.info(f"[CLEAN] ✅ Clean xong {len(lines)} dòng trong {elapsed:.2f}s")
    return cleaned_lines
