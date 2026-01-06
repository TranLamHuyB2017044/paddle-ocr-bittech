"""
OCR Utilities
Các hàm tiện ích cho OCR extraction
"""
import time
from datetime import datetime
from src.models.model_loader import model_loader
from src.utils.logger import Log

import cv2
import os

def preprocess_for_ocr(path):
    """
    Tiền xử lý ảnh trong bộ nhớ (In-memory) để tăng tốc
    Returns:
        numpy.ndarray: Ảnh đã được xử lý
    """
    img = cv2.imread(path)
    if img is None:
        Log.error(f"[PREPROCESS] ❌ Cannot read image: {path}")
        return None
        
    h, w = img.shape[:2]

    # Resize logic: Giữ độ phân giải đủ cao nhưng không quá nặng
    max_side = 960
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        Log.info(f"[PREPROCESS] 📉 Resized {w}x{h} -> {new_w}x{new_h}")

    return img

def ocr_extract(image_path, retry_mode=False):
    """
    Trích xuất text từ ảnh sử dụng OCR hiệu năng cao (In-memory processing)
    Returns:
        list_of_dicts: [{'text': str, 'box': list, 'score': float}, ...]
        raw_text_list: [str, str, ...]
    """

    start = time.time()
    Log.info(f"[OCR] 🔍 Bắt đầu OCR (In-memory): {image_path}")

    # 1. Tiền xử lý trực tiếp trong RAM
    processed_img = preprocess_for_ocr(image_path)
    if processed_img is None:
        return [], []

    # 2. Gọi OCR với ảnh từ RAM
    result = model_loader.ocr.predict(processed_img)

    block = result[0]
    ocr_data = [] 
    texts = []    
    import numpy as np

    if block:
        target_dict = None
        if isinstance(block, dict) and "rec_texts" in block:
             target_dict = block
        elif isinstance(result, dict) and "res" in result: 
             target_dict = result["res"]
        elif isinstance(block, dict) and "res" in block:
             target_dict = block["res"]
             
        if target_dict and "rec_texts" in target_dict:
            r_texts = target_dict.get("rec_texts", [])
            r_scores = target_dict.get("rec_scores", [])
            r_boxes = target_dict.get("dt_polys") or target_dict.get("rec_boxes") or target_dict.get("rec_polys")
            
            for i in range(len(r_texts)):
                txt = r_texts[i] or ""
                score = float(r_scores[i]) if len(r_scores) > i else 1.0
                box = r_boxes[i].tolist() if r_boxes is not None and len(r_boxes) > i else [[0,0], [0,0], [0,0], [0,0]]
                texts.append(txt)
                ocr_data.append({"text": txt, "box": box, "score": score})
        elif isinstance(block, list):
             for item in block:
                 if len(item) >= 2:
                     box = item[0]
                     text_val, score_val = item[1]
                     texts.append(text_val)
                     ocr_data.append({"text": text_val, "box": box, "score": score_val})

    Log.info(f"[OCR] ✅ Hoàn tất. Lines: {len(ocr_data)}. Thời gian: {time.time() - start:.2f}s")
    return ocr_data, texts


def filter_useless_lines(ocr_data):
    from src.config import USELESS_KEYWORDS
    from rapidfuzz import fuzz
    
    is_legacy_input = False
    if len(ocr_data) > 0 and isinstance(ocr_data[0], str):
        is_legacy_input = True
    
    input_count = len(ocr_data)
    Log.info(f"[FILTER] 🗑️  Bắt đầu lọc text không cần thiết. Số dòng: {input_count}")
    
    if input_count == 0:
        return []
    
    filtered = []
    removed_count = 0
    
    for item in ocr_data:
        # Extract text content depending on format
        if is_legacy_input:
            line_text = item
        else:
            line_text = item.get("text", "")

        line_lower = line_text.lower().strip()
        
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
                if len(keyword) < 4: continue
                score = fuzz.partial_ratio(keyword, line_lower)
                if score >= 85:
                    is_useless = True
                    matched_keyword = f"{keyword} (fuzzy {score:.0f}%)"
                    break

        if is_useless:
            Log.debug(f"[FILTER] ❌ Loại bỏ: '{line_text[:50]}...' [Match: {matched_keyword}]")
            removed_count += 1
        else:
            filtered.append(item)
    
    Log.info(f"[FILTER] 📊 Kết quả: Loại bỏ {removed_count} dòng, Còn lại {len(filtered)} dòng")
    
    return filtered
