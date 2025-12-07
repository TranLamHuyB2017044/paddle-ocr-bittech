"""
OCR Utilities
Các hàm tiện ích cho OCR extraction
"""
import time
from datetime import datetime
from cccd.models.model_loader import model_loader
from cccd.utils.logger import Log


def ocr_extract(image_path):
    """
    Trích xuất text từ ảnh sử dụng OCR
    
    Args:
        image_path: Đường dẫn đến file ảnh
        
    Returns:
        tuple: (list of text lines, list of confidence scores)
    """
    start_time = time.time()
    Log.info(f"[OCR] 🔍 Bắt đầu OCR: {image_path}")
    
    # Sử dụng OCR từ model_loader
    result = model_loader.ocr.predict(image_path)
    
    for block in result:
        elapsed = time.time() - start_time
        num_lines = len(block["rec_texts"])
        Log.info(f"[OCR] ✅ Hoàn thành OCR. Số dòng: {num_lines}. Thời gian: {elapsed:.2f}s")
        
        # 📋 LOG CHI TIẾT
        Log.debug(f"[OCR] 📋 CHI TIẾT TEXT DETECT:")
        for i, (text, score) in enumerate(zip(block["rec_texts"], block["rec_scores"]), 1):
            confidence = score * 100
            emoji = "✅" if confidence >= 80 else "⚠️" if confidence >= 60 else "❌"
            Log.debug(f"[OCR] {emoji} [{i:2d}] [{confidence:5.1f}%] {text[:70]}")
        
        return block["rec_texts"], block["rec_scores"]
    
    Log.warning(f"[OCR] ⚠️  Không tìm thấy text")
    return [], []


def filter_useless_lines(lines):
    """
    Lọc bỏ các dòng text chung không cần thiết
    
    Args:
        lines: Danh sách các dòng text
        
    Returns:
        list: Danh sách các dòng text đã được lọc
    """
    from cccd.config import USELESS_KEYWORDS
    
    Log.info(f"[FILTER] 🗑️  Bắt đầu lọc text không cần thiết. Số dòng: {len(lines)}")
    
    # ⚠️ Kiểm tra input rỗng
    if len(lines) == 0:
        Log.warning(f"[FILTER] ⚠️  CẢNH BÁO: Không có dòng text nào từ OCR!")
        return []
    
    filtered = []
    removed_count = 0
    
    for line in lines:
        line_lower = line.lower().strip()
        
        # Bỏ qua dòng rỗng
        if not line_lower:
            continue
        
        # Kiểm tra xem có chứa từ khóa không cần thiết không
        is_useless = False
        matched_keyword = ""
        
        for keyword in USELESS_KEYWORDS:
            if keyword in line_lower:
                is_useless = True
                matched_keyword = keyword
                removed_count += 1
                break
        
        if is_useless:
            Log.debug(f"[FILTER] ❌ Loại bỏ (từ khóa '{matched_keyword}'): '{line[:60]}'")
        else:
            filtered.append(line)
            Log.debug(f"[FILTER] ✅ Giữ lại: '{line[:60]}'")
    
    Log.info(f"[FILTER] 📊 Kết quả: Loại bỏ {removed_count} dòng, Còn lại {len(filtered)} dòng")
    
    return filtered
