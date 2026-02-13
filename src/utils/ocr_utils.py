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
import threading

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
    Log.info(f"[PREPROCESS] 📸 Original size: {w}x{h}")

    # Resize logic: Giữ độ phân giải đủ cao nhưng không quá nặng
    max_side = 960
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        Log.info(f"[PREPROCESS] 📉 Resized {w}x{h} -> {new_w}x{new_h}")
    else:
        Log.info(f"[PREPROCESS] ✅ Size is within limit ({w}x{h})")

    return img

def ocr_extract(image_path, img=None, retry_mode=False):
    """
    Trích xuất text từ ảnh sử dụng OCR hiệu năng cao (In-memory processing)
    Returns:
        list_of_dicts: [{'text': str, 'box': list, 'score': float}, ...]
        raw_text_list: [str, str, ...]
    """

    start = time.time()
    Log.info(f"[OCR] 🔍 Bắt đầu OCR (In-memory): {image_path}")

    # 1. Tiền xử lý trực tiếp trong RAM (Chỉ load nếu chưa có img)
    processed_img = img if img is not None else preprocess_for_ocr(image_path)
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
    """
    [DEPRECATED] Cũ, đã loại bỏ theo yêu cầu.
    """
    return ocr_data


def filter_back_side_lines(ocr_data):
    """
    [DEPRECATED] Cũ, đã loại bỏ theo yêu cầu.
    """
    return ocr_data
