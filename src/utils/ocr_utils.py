"""
OCR Utilities
Các hàm tiện ích cho OCR extraction tối giản.
"""
import time
import cv2
import os
from ..models.model_loader import model_loader
from .logger import Log

def preprocess_for_ocr(path_or_img, max_side=None):
    """
    Tiền xử lý ảnh: Resize và làm sắc nét nhẹ để tối ưu OCR.
    """
    import numpy as np
    img = None
    
    if isinstance(path_or_img, str):
        if not os.path.exists(path_or_img):
            Log.error(f"[PREPROCESS] ❌ Cannot find image at: {path_or_img}")
            return None
        img = cv2.imread(path_or_img)
    elif isinstance(path_or_img, np.ndarray):
        img = path_or_img
        
    if img is None: return None
        
    h, w = img.shape[:2]

    # 1. Resize logic
    if max_side is None:
        try:
            from ..config import OCR_CONFIG
            max_side = OCR_CONFIG.get("det_limit_side_len", 960)
        except:
            max_side = 960

    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    # 2. Sắc nét nhẹ (Unsharp Mask) - Quan trọng cho Tiếng Việt
    gaussian_blur = cv2.GaussianBlur(img, (0, 0), 2.0)
    final_img = cv2.addWeighted(img, 1.5, gaussian_blur, -0.5, 0)

    return final_img

def ocr_extract(image_path, img=None):
    """
    Trích xuất text thô (OCR V5).
    """
    start = time.time()
    processed_img = img if img is not None else preprocess_for_ocr(image_path)
    if processed_img is None: return [], []

    result = model_loader.ocr.predict(processed_img)
    ocr_data = [] 
    texts = []    

    if result and result[0]:
        for line in result[0]:
            if isinstance(line, list) and len(line) >= 2:
                box = line[0]
                text_val, score_val = line[1]
                texts.append(text_val)
                ocr_data.append({"text": text_val, "box": box, "score": score_val})

    Log.info(f"[OCR] ✅ Done. Lines: {len(ocr_data)}. Time: {time.time() - start:.2f}s")
    return ocr_data, texts

def ocr_structure_extract(image_path, img=None):
    """
    Trích xuất vùng cấu trúc (PP-Structure V3).
    """
    start = time.time()
    processed_img = img if img is not None else preprocess_for_ocr(image_path)
    if processed_img is None: return [], []

    # predict
    preds = model_loader.structure.predict(processed_img)
    pred_obj = list(preds)[0] if preds else None
    
    if not pred_obj: return [], []
    
    # Extract blocks
    result = []
    if hasattr(pred_obj, '__getitem__') and 'parsing_res_list' in pred_obj:
        result = pred_obj['parsing_res_list']
    else:
        result = pred_obj if isinstance(pred_obj, list) else []

    formatted_results = []
    log_text = []

    for region in result:
        # PaddleX Object format
        if hasattr(region, 'label') and hasattr(region, 'content'):
            rtype, content = getattr(region, 'label'), getattr(region, 'content')
            bbox = getattr(region, 'bbox', [])
            log_text.append(f"[{rtype.upper()}] {content[:50]}...")
            formatted_results.append({"type": rtype, "content": content, "box": bbox})
        # Dict format
        elif isinstance(region, dict):
            rtype = region.get('type', '')
            res = region.get('res', {})
            content = res.get('html', '') if rtype == 'table' else " ".join([line.get('text', '') if isinstance(line, dict) else str(line) for line in (res if isinstance(res, list) else [])])
            formatted_results.append({"type": rtype, "content": content, "box": region.get('bbox', [])})

    Log.info(f"[Structure] ✅ Done. Regions: {len(formatted_results)}. Time: {time.time() - start:.2f}s")
    return formatted_results, log_text

def smart_menu_ocr_extract(image_path, img=None):
    """
    Gom nhóm dòng cho Menu/Hóa đơn đơn giản.
    """
    ocr_data, _ = ocr_extract(image_path, img=img)
    if not ocr_data: return [], []
        
    boxes = []
    for item in ocr_data:
        box = item['box']
        y_center = sum(p[1] for p in box) / 4.0
        h = max(p[1] for p in box) - min(p[1] for p in box)
        boxes.append({'text': item['text'], 'x': box[0][0], 'y': y_center, 'h': h})

    boxes.sort(key=lambda b: b['y'])
    lines = []
    if boxes:
        cur_line = [boxes[0]]
        for b in boxes[1:]:
            if abs(b['y'] - (sum(x['y'] for x in cur_line)/len(cur_line))) < (cur_line[0]['h'] * 0.6):
                cur_line.append(b)
            else:
                lines.append(cur_line)
                cur_line = [b]
        lines.append(cur_line)

    res = []
    for l in lines:
        l.sort(key=lambda b: b['x'])
        res.append({"type": "text", "content": " - ".join([b['text'] for b in l])})
    
    return res, [r['content'] for r in res]

def filter_useless_lines(ocr_data):
    """Pass-through filter."""
    return ocr_data

def filter_back_side_lines(ocr_data):
    """Pass-through filter."""
    return ocr_data
