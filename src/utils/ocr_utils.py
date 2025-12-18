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

def ocr_extract(image_path, retry_mode=False):
    """
    Trích xuất text từ ảnh sử dụng OCR với preprocessing
    Returns:
        list_of_dicts: [{'text': str, 'box': list, 'score': float}, ...]
        raw_text_list: [str, str, ...] (for legacy compatibility if needed)
    """

    start = time.time()
    Log.info(f"[OCR] 🔍 Bắt đầu OCR: {image_path}")

    # Resize trước khi OCR
    small_path = preprocess_for_ocr(image_path)

    # Gọi OCR
    result = model_loader.ocr.predict(small_path)

    block = result[0]
    
    ocr_data = [] # New rich format
    texts = []    # Legacy format

    import numpy as np

    if block:
        # CASE 1: New Dict Format (The one user provided)
        # Check keys directly on block (if block is dict) or result (if result is dict but singular)
        # Based on user input: {'res': ...} but paddleocr often returns [res_dict] or [[lines]].
        # Let's handle 'rec_texts' existing in block.
        
        target_dict = None
        if isinstance(block, dict) and "rec_texts" in block:
             target_dict = block
        elif isinstance(result, dict) and "res" in result: # Outer wrapper
             target_dict = result["res"]
        elif isinstance(block, dict) and "res" in block:
             target_dict = block["res"]
             
        if target_dict and "rec_texts" in target_dict:
            r_texts = target_dict.get("rec_texts", [])
            r_scores = target_dict.get("rec_scores", [])
            # Prefer dt_polys (detection polys) or rec_boxes
            r_boxes = target_dict.get("dt_polys") 
            if r_boxes is None: r_boxes = target_dict.get("rec_boxes")
            if r_boxes is None: r_boxes = target_dict.get("rec_polys")
            
            # Ensure length match
            count = len(r_texts)
            for i in range(count):
                txt = r_texts[i]
                if txt is None: txt = ""
                
                # Score
                score = 1.0
                if len(r_scores) > i:
                    score = float(r_scores[i])
                    
                # Box
                box = [[0,0], [0,0], [0,0], [0,0]]
                if r_boxes is not None and len(r_boxes) > i:
                    # Convert numpy dict to list
                    b = r_boxes[i]
                    if isinstance(b, np.ndarray):
                        b = b.tolist()
                    box = b
                
                texts.append(txt)
                ocr_data.append({
                    "text": txt,
                    "box": box,
                    "score": score
                })
                
        # CASE 2: Standard Paddle List of Tuples Format [[box, (text, score)], ...]
        elif isinstance(block, list):
             for item in block:
                 # item structure: [box, (text, score)]
                 if len(item) >= 2:
                     box = item[0]
                     text_obj = item[1]
                     text_val = text_obj[0]
                     score_val = text_obj[1]
                     
                     texts.append(text_val)
                     ocr_data.append({
                         "text": text_val,
                         "box": box,
                         "score": score_val
                     })

    Log.info(
        f"[OCR] ✅ OCR xong. Lines: {len(ocr_data)}. "
        f"Thời gian: {time.time() - start:.2f}s"
    )

    # --- AUTO-ROTATION CHECK (If Classifier Failed) ---
    if not retry_mode and ocr_data and len(ocr_data) > 3: # Only check if we have enough lines
        vertical_boxes = 0
        for item in ocr_data:
            box = item['box']
            # box: [[x1,y1], [x2,y2], [x3,y3], [x4,y4]]
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            w = max(xs) - min(xs)
            h = max(ys) - min(ys)
            if h > w * 1.5: # Clearly vertical
                vertical_boxes += 1
        
        # If > 50% boxes are vertical, image is likely rotated 90 degrees
        if vertical_boxes > len(ocr_data) * 0.5:
            Log.warning("[OCR] 🔄 Phát hiện ảnh bị xoay dọc. Đang thử xoay và kiểm tra...")
            
            # Keywords to validate used rotation
            VALIDATION_KEYWORDS = ["Cộng hòa", "Socialist", "Identity", "Driver", "Giấy phép", "Chiến sĩ", "Hóa đơn", "Reciept"]
            
            try:
                import cv2
                import numpy as np
                
                img = cv2.imread(small_path)
                if img is not None:
                    # --- ATTEMPT 1: Rotate 90 Clockwise (Most common) ---
                    Log.info("[OCR] ↪️ Thử xoay 90 độ Clockwise...")
                    rotated_img_cw = cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
                    
                    rot_path = small_path.replace(".", "_rotated_cw.")
                    cv2.imwrite(rot_path, rotated_img_cw)
                    
                    try:
                        data_cw, texts_cw = ocr_extract(rot_path, retry_mode=True)
                        
                        # Validate
                        is_valid = any(kw.lower() in t.lower() for t in texts_cw for kw in VALIDATION_KEYWORDS)
                        
                        if is_valid:
                            Log.info("[OCR] ✅ Xoay Clockwise thành công (khớp từ khóa).")
                            if os.path.exists(rot_path): os.remove(rot_path)
                            return data_cw, texts_cw
                        else:
                            Log.warning("[OCR] ⚠️ Xoay Clockwise không ra từ khóa chuẩn. Thử xoay ngược lại...")
                    except Exception:
                        pass
                    
                    # --- ATTEMPT 2: Rotate 90 Counter-Clockwise ---
                    # Only runs if Attempt 1 failed validation
                    Log.info("[OCR] ↩️ Thử xoay 90 độ Counter-Clockwise...")
                    rotated_img_ccw = cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
                    
                    rot_path_ccw = small_path.replace(".", "_rotated_ccw.")
                    cv2.imwrite(rot_path_ccw, rotated_img_ccw)
                    
                    data_ccw, texts_ccw = ocr_extract(rot_path_ccw, retry_mode=True)
                    
                    # Clean up
                    if os.path.exists(rot_path): os.remove(rot_path)
                    if os.path.exists(rot_path_ccw): os.remove(rot_path_ccw)
                    
                    return data_ccw, texts_ccw

            except Exception as e:
                Log.error(f"[OCR] ❌ Lỗi khi xoay ảnh: {e}")
                # Fallback to original result

    return ocr_data, texts


def filter_useless_lines(ocr_data):
    """
    Lọc bỏ các dòng text chung không cần thiết
    
    Args:
        ocr_data: List dictionaries [{'text':..., 'box':...}] (New Format)
                  OR List strings (Legacy Format support)
        
    Returns:
        Same type as input (filtered)
    """
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
