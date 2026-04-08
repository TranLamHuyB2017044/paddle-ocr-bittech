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

def preprocess_for_ocr(path_or_img):
    """
    Tiền xử lý ảnh: Resize, tăng độ tương phản và khử nhiễu để tối ưu OCR
    Returns:
        numpy.ndarray: Ảnh đã được xử lý
    """
    import numpy as np
    img = None
    
    if isinstance(path_or_img, str):
        if not os.path.exists(path_or_img):
            Log.error(f"[PREPROCESS] ❌ Cannot find image at path: {path_or_img}")
            return None
        img = cv2.imread(path_or_img)
    elif isinstance(path_or_img, np.ndarray):
        img = path_or_img
        
    if img is None:
        Log.error(f"[PREPROCESS] ❌ Cannot read image: {path_or_img}")
        return None
        
    h, w = img.shape[:2]
    Log.info(f"[PREPROCESS] 📸 Original size: {w}x{h}")

    # 1. Resize logic: Giữ độ phân giải đủ cao
    max_side = 1536 
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        Log.info(f"[PREPROCESS] 📉 Resized {w}x{h} -> {new_w}x{new_h}")

    # CẢI THIỆN OCR CHẤT LƯỢNG CAO CHO CCCD:
    # 2. Không chuyển sang Grayscale hay làm mờ nhiễu (GaussianBlur cỡ lớn) 
    # vì sẽ làm dính các dấu tiếng Việt (hỏi, ngã, nặng) và tiêu hủy nét nhỏ.
    # PaddleOCR V5 được tối ưu cho ảnh màu BGR.
    
    # Sử dụng kỹ thuật Unsharp Masking nhẹ để làm sắc nét viền chữ
    gaussian_blur = cv2.GaussianBlur(img, (0, 0), 2.0)
    final_img = cv2.addWeighted(img, 1.5, gaussian_blur, -0.5, 0)

    # Nếu ảnh gốc quá sáng/tối có thể cân nhắc LAB CLAHE trên kênh màu L để không hư màu, 
    # nhưng mặc định Unsharp Masking trên BGR là an toàn nhất cho chữ.

    # ---> LƯU ẢNH DEBUG VÀO THƯ MỤC TẠM ĐỂ XEM LẠI <---
    try:
        from src.config import UPLOAD_FOLDER
        debug_dir = os.path.join(UPLOAD_FOLDER, "debug_ocr")
        os.makedirs(debug_dir, exist_ok=True)
        
        # Tạo tên file
        if isinstance(path_or_img, str):
            base_name = os.path.basename(path_or_img)
            debug_path = os.path.join(debug_dir, f"preprocessed_{base_name}")
        else:
            debug_path = os.path.join(debug_dir, f"preprocessed_{int(time.time()*1000)}.jpg")
            
        cv2.imwrite(debug_path, final_img)
        Log.info(f"[PREPROCESS] 💾 Saved debug image to: {debug_path}")
    except Exception as e:
        Log.error(f"[PREPROCESS] ❌ Failed to save debug image: {e}")

    Log.info(f"[PREPROCESS] ✨ Image enhancement applied (Unsharp Mask on BGR)")
    return final_img

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

def ocr_structure_extract(image_path, img=None):
    """
    Trích xuất cấu trúc từ ảnh (Layout + Table) sử dụng PP-Structure V3
    Đặc biệt tối ưu cho Menu và Hóa đơn.
    Returns:
        list_of_dicts: Kết quả thô từ structure engine
        structured_text: Văn bản đã được định dạng theo cấu trúc (HTML table, v.v.)
    """
    start = time.time()
    Log.info(f"[Structure] 🏗️ Bắt đầu trích xuất cấu trúc: {image_path}")

    processed_img = img if img is not None else preprocess_for_ocr(image_path)
    if processed_img is None:
        return [], []

    # Gọi PP-Structure (Hỗ trợ cả v2 call và v3 Pipeline)
    if hasattr(model_loader.structure, 'predict'):
        preds = model_loader.structure.predict(processed_img)
        # return list of PipelineResult
        pred_obj = list(preds)[0] if preds else None
        
        # PipelineResult in PaddleX stores layout blocks in 'parsing_res_list'
        if pred_obj and hasattr(pred_obj, '__getitem__') and 'parsing_res_list' in pred_obj:
            result = pred_obj['parsing_res_list']
        elif pred_obj and isinstance(pred_obj, dict) and 'layout_res' in pred_obj:
            result = pred_obj['layout_res']
        else:
            result = pred_obj if pred_obj else []
    else:
        result = model_loader.structure(processed_img)
    
    # Validation fallback
    if type(result).__name__ in ['PipelineResult', 'DocParserResult', 'LayoutParsingResultV2']:
        Log.warning(f"[Structure] Result is still PipelineResult object. Trying to extract parsing_res_list...")
        try:
            result = result['parsing_res_list']
        except Exception:
            result = []
    
    if not isinstance(result, list):
        if isinstance(result, dict) and 'type' in result:
            result = [result]
        elif hasattr(result, '__iter__') and not isinstance(result, dict):
            result = list(result)
        else:
            result = []

    # PP-Structure return list of results for each image
    formatted_results = []
    log_text = []

    for region in result:
        # Support PaddleX LayoutBlock object
        if hasattr(region, 'label') and hasattr(region, 'content'):
            region_type = getattr(region, 'label')
            content = getattr(region, 'content')
            bbox = getattr(region, 'bbox', getattr(region, 'box', []))
            
            if region_type == 'table':
                log_text.append(f"[TABLE]\n{content}")
                formatted_results.append({
                    "type": "table",
                    "content": content,
                    "cells": [],
                    "box": bbox
                })
            else:
                log_text.append(f"[{region_type.upper()}] {content}")
                formatted_results.append({
                    "type": region_type,
                    "content": content,
                    "box": bbox
                })
            continue

        # Support old PaddleOCR V2 Dict format
        if isinstance(region, dict):
            region_type = region.get('type', '')
            res = region.get('res', {})
        
        if region_type == 'table':
            # Với table, lấy nội dung HTML hoặc các dòng text đã được group
            html = res.get('html', '')
            log_text.append(f"[TABLE]\n{html}")
            formatted_results.append({
                "type": "table",
                "content": html,
                "cells": res.get('cell_bbox', []),
                "box": region.get('bbox', [])
            })
        else:
            # Với text/header/..., lấy text lines
            lines = []
            if isinstance(res, list):
                for line in res:
                    if isinstance(line, dict):
                        lines.append(line.get('text', ''))
                    elif isinstance(line, list) and len(line) > 1:
                        # Thường là [box, (text, score)]
                        lines.append(line[1][0])
            
            combined_text = " ".join(lines)
            log_text.append(f"[{region_type.upper()}] {combined_text}")
            formatted_results.append({
                "type": region_type,
                "content": combined_text,
                "box": region.get('bbox', [])
            })

    # Log kết quả OCR thô
    Log.info("\n" + "-"*20 + "\n[Structure OCR RAW OUTPUT]:\n" + "\n".join(log_text) + "\n" + "-"*20)
    
    Log.info(f"[Structure] ✅ Hoàn tất. Vùng nhận diện: {len(formatted_results)}. Thời gian: {time.time() - start:.2f}s")
    return formatted_results, log_text




def smart_menu_ocr_extract(image_path, img=None):
    """
    Sử dụng OCR Box để gom nhóm các từ theo cùng một dòng (chứa tên món + giá),
    và tự động phân loại Category Title dựa vào độ cao của box chữ (font size lớn).
    """
    start = time.time()
    Log.info(f"[SmartMenu] 🧠 Starting smart menu extraction: {image_path}")
    
    # 1. Chạy raw OCR
    ocr_data, _ = ocr_extract(image_path, img=img)
    if not ocr_data:
        return [], []
        
    # Tính toán chiều cao và tọa độ trung tâm Y
    boxes_info = []
    total_height = 0
    for item in ocr_data:
        box = item['box']
        y_min = min(p[1] for p in box)
        y_max = max(p[1] for p in box)
        x_min = min(p[0] for p in box)
        x_max = max(p[0] for p in box)
        height = y_max - y_min
        boxes_info.append({
            'text': item['text'],
            'x_min': x_min, 'x_max': x_max,
            'y_min': y_min, 'y_max': y_max,
            'y_center': (y_min + y_max) / 2.0,
            'height': height
        })
        total_height += height

    avg_height = total_height / len(boxes_info) if boxes_info else 0

    # 2. Sắp xếp các box từ trên xuống dưới
    boxes_info.sort(key=lambda b: b['y_center'])

    # 3. Gom nhóm theo cùng dòng
    lines = []
    if boxes_info:
        current_line = [boxes_info[0]]
        for box in boxes_info[1:]:
            line_y_center = sum(b['y_center'] for b in current_line) / len(current_line)
            line_height = sum(b['height'] for b in current_line) / len(current_line)
            
            # Nếu chênh lệch Y nhỏ hơn 60% chiều cao của dòng, gộp vào cùng dòng
            if abs(box['y_center'] - line_y_center) < (line_height * 0.6):
                current_line.append(box)
            else:
                lines.append(current_line)
                current_line = [box]
        lines.append(current_line)

    # 4. Định dạng và phân loại Title vs Text
    formatted_results = []
    log_text = []
    
    # Title là những chữ lớn hơn 35% so với bình thường
    title_height_threshold = avg_height * 1.35 

    for line_boxes in lines:
        # Sort boxes trong dòng từ trái sang phải
        line_boxes.sort(key=lambda b: b['x_min'])
        
        # Món ăn thường là text, category là chữ to
        max_line_height = max(b['height'] for b in line_boxes)
        is_title = max_line_height >= title_height_threshold
        
        # Ngăn cách Tên món và Giá tiền bằng dấu " - " để AI dễ phân biệt
        combined_text = " - ".join([b['text'] for b in line_boxes])
        
        if is_title:
            content = f"--- DANH MỤC: {combined_text.upper()} ---"
            log_text.append(content)
            formatted_results.append({"type": "title", "content": content})
        else:
            log_text.append(combined_text)
            formatted_results.append({"type": "text", "content": combined_text})

    Log.info("\n" + "-"*20 + "\n[Smart Menu RAW OUTPUT]:\n" + "\n".join(log_text) + "\n" + "-"*20)
    Log.info(f"[SmartMenu] ✅ Hoàn tất. Dòng: {len(formatted_results)}. Thời gian: {time.time() - start:.2f}s")
    
    return formatted_results, log_text

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
