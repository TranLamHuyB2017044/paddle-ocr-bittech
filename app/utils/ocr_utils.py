"""
OCR Utilities
Các hàm tiện ích cho OCR extraction
"""
import time
from datetime import datetime
from app.models.model_loader import model_loader
from app.utils.logger import Log

import cv2

def preprocess_for_ocr(path):
    img = cv2.imread(path)
    if img is None:
        Log.error(f"[PREPROCESS] ❌ Cannot read image: {path}")
        return path # Return original path if resize fails
        
    h, w = img.shape[:2]

    # Resize logic: Downscale if largest side > 960 (Balance speed/accuracy)
    max_side = 960
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        Log.info(f"[PREPROCESS] 📉 Resized {w}x{h} -> {new_w}x{new_h}")

    # Overwrite original file to save space and simplify cleanup
    # (Since we don't need the high-res original for OCR)
    try:
        cv2.imwrite(path, img, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        return path
    except Exception as e:
        Log.error(f"[PREPROCESS] ⚠️ Failed to overwrite image: {e}")
        return path

def ocr_extract(image_path):
    """
    Trích xuất text từ ảnh sử dụng OCR với preprocessing
    """

    start = time.time()
    Log.info(f"[OCR] 🔍 Bắt đầu OCR: {image_path}")

    # Resize trước khi OCR
    small_path = preprocess_for_ocr(image_path)

    # Gọi OCR
    result = model_loader.ocr.predict(small_path)

    if not result:
        Log.warning("[OCR] ⚠️ Không tìm thấy text")
        return [], []

    block = result[0]
    texts = block["rec_texts"]
    scores = block["rec_scores"]

    Log.info(
        f"[OCR] ✅ OCR xong. Lines: {len(texts)}. "
        f"Thời gian: {time.time() - start:.2f}s"
    )

    return texts, scores


def filter_useless_lines(lines):
    """
    Lọc bỏ các dòng text chung không cần thiết
    
    Args:
        lines: Danh sách các dòng text
        
    Returns:
        list: Danh sách các dòng text đã được lọc
    """
    from app.config import USELESS_KEYWORDS
    from rapidfuzz import fuzz
    
    Log.info(f"[FILTER] 🗑️  Bắt đầu lọc text không cần thiết. Số dòng: {len(lines)}")
    
    # ⚠️ Kiểm tra input rỗng
    if len(lines) == 0:
        Log.warning(f"[FILTER] ⚠️  CẢNH BÁO: Không có dòng text nào từ OCR!")
        return []
    
    filtered = []
    removed_count = 0
    
    for line in lines:
        line_lower = line.lower().strip()
        
        # Bỏ qua dòng rỗng hoặc quá ngắn
        if len(line_lower) < 2:
            continue
        
        # Kiểm tra xem có chứa từ khóa không cần thiết không
        is_useless = False
        matched_keyword = ""
        
        # 1. Check exact/partial match (Faster)
        for keyword in USELESS_KEYWORDS:
             if keyword in line_lower:
                 is_useless = True
                 matched_keyword = keyword
                 break
        
        # 2. Check Fuzzy match (Slower but catches OCR errors)
        if not is_useless:
            for keyword in USELESS_KEYWORDS:
                # Nếu từ khóa quá ngắn, fuzzy rất dễ sai -> skip
                if len(keyword) < 4: continue
                
                # Check tỷ lệ trùng khớp (partial_ratio)
                # Tỷ lệ > 85% coi như là trùng
                score = fuzz.partial_ratio(keyword, line_lower)
                if score >= 85:
                    is_useless = True
                    matched_keyword = f"{keyword} (fuzzy {score:.0f}%)"
                    break

        if is_useless:
            Log.debug(f"[FILTER] ❌ Loại bỏ: '{line[:50]}...' [Match: {matched_keyword}]")
            removed_count += 1
        else:
            filtered.append(line)
            # Log.debug(f"[FILTER] ✅ Giữ lại: '{line[:50]}...'")
    
    Log.info(f"[FILTER] 📊 Kết quả: Loại bỏ {removed_count} dòng, Còn lại {len(filtered)} dòng")
    
    return filtered
