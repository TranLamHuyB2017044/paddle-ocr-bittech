"""
OCR Utilities
Các hàm tiện ích cho OCR extraction – sử dụng DeepDoc + VietOCR
Output format không đổi để tương thích ngược với toàn bộ codebase.
"""
import time
import os
import threading

import cv2
import numpy as np

from src.shared.models.model_loader import model_loader
from src.shared.utils.logger import Log


# ============================================================
# Preprocessing
# ============================================================

def preprocess_for_ocr(path_or_img):
    """
    Tiền xử lý ảnh: Resize, tăng độ tương phản và khử nhiễu để tối ưu OCR.
    Returns:
        numpy.ndarray: Ảnh BGR đã được xử lý (hoặc None nếu lỗi)
    """
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

    # 1. Resize: Giữ độ phân giải đủ cao
    max_side = 960 
    if max(h, w) > max_side:
        scale = max_side / max(h, w)
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = cv2.resize(img, (new_w, new_h), interpolation=cv2.INTER_AREA)
        Log.info(f"[PREPROCESS] 📉 Resized {w}x{h} -> {new_w}x{new_h}")

    # 2. Chuyển sang ảnh xám
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 3. CLAHE - tăng độ tương phản cục bộ
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # 4. Bỏ qua blur để giữ dấu Tiếng Việt sắc nét
    final_img = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)

    Log.info("[PREPROCESS] ✨ Image enhancement applied (CLAHE)")
    return final_img


# ============================================================
# Core OCR extract
# ============================================================

def ocr_extract(image_path, img=None, retry_mode=False, detect_handwriting=False):
    """
    Trích xuất text từ ảnh sử dụng DeepDoc + VietOCR.
    
    Args:
        image_path: str – đường dẫn ảnh (dùng khi img=None)
        img: numpy.ndarray – ảnh BGR đã load sẵn (ưu tiên dùng nếu có)
        retry_mode: bool – không dùng trong bản này (để tương thích API cũ)
        detect_handwriting: bool – sử dụng model VietOCR finetuned cho chữ viết tay
    
    Returns:
        ocr_data: list[dict] – [{'text': str, 'box': list, 'score': float}, ...]
        texts: list[str] – danh sách text thuần tuý
    """
    start = time.time()
    Log.info(f"[OCR] 🔍 Bắt đầu OCR (DeepDoc+VietOCR{' Handwritten' if detect_handwriting else ''}): {image_path}")

    # Chuẩn bị ảnh
    processed_img = img if img is not None else preprocess_for_ocr(image_path)
    if processed_img is None:
        return [], []

    ocr_data = []
    texts = []

    try:
        if detect_handwriting:
            from PIL import Image
            import copy
            
            if model_loader.ocr is None:
                raise Exception("OCR engine is not loaded")
                
            ocr_engine = model_loader.ocr.engine
            dt_boxes, _elapse = ocr_engine.text_detector[0](processed_img)
            
            if dt_boxes is not None:
                dt_boxes = ocr_engine.sorted_boxes(dt_boxes)
                predictor = model_loader.handwritten_predictor
                if not predictor:
                    raise Exception("Cannot load handwritten predictor")
                    
                for bno in range(len(dt_boxes)):
                    tmp_box = copy.deepcopy(dt_boxes[bno])
                    img_crop = ocr_engine.get_rotate_crop_image(processed_img, tmp_box)
                    # predictor expects PIL Image RGB
                    pil_img = Image.fromarray(cv2.cvtColor(img_crop, cv2.COLOR_BGR2RGB))
                    text = predictor.predict(pil_img)
                    
                    texts.append(text)
                    ocr_data.append({"text": text, "box": tmp_box.tolist(), "score": 1.0})
        else:
            if model_loader.ocr is None:
                raise Exception("OCR engine is not loaded")
                
            raw_results = model_loader.ocr(processed_img)
            if raw_results:
                for item in raw_results:
                    # item = (box, (text, score)) theo format DeepDocOCR
                    if len(item) < 2:
                        continue
                    box = item[0]       # [[x0,y0],[x1,y1],[x2,y2],[x3,y3]]
                    text_info = item[1] # (text, score)
                    
                    if isinstance(text_info, (list, tuple)) and len(text_info) >= 2:
                        text = str(text_info[0]) if text_info[0] else ""
                        score = float(text_info[1])
                    elif isinstance(text_info, str):
                        text = text_info
                        score = 1.0
                    else:
                        continue
                    
                    texts.append(text)
                    ocr_data.append({"text": text, "box": box, "score": score})

    except Exception as e:
        Log.error(f"[OCR] ❌ OCR engine error: {e}")
        return [], []

    Log.info(f"[OCR] ✅ Hoàn tất. Lines: {len(ocr_data)}. Thời gian: {time.time() - start:.2f}s")
    return ocr_data, texts


# ============================================================
# Structure extract (simplified – dùng ocr_extract thay vì PP-Structure)
# ============================================================

def ocr_structure_extract(image_path, img=None):
    """
    Trích xuất cấu trúc từ ảnh.
    Note: PP-Structure V3 đã bị loại bỏ cùng PaddleOCR.
    Hàm này fallback về ocr_extract thông thường để duy trì tương thích API.
    Với tài liệu phức tạp (invoice, table), khuyến nghị dùng AI (OpenAI) processor.
    
    Returns:
        formatted_results: list[dict] với keys 'type', 'content', 'box'
        log_text: list[str]
    """
    start = time.time()
    Log.info(f"[Structure] 🏗️ Bắt đầu trích xuất (fallback to ocr_extract): {image_path}")

    ocr_data, _ = ocr_extract(image_path, img=img)
    
    formatted_results = []
    log_text = []
    
    for item in ocr_data:
        text = item.get('text', '')
        box = item.get('box', [])
        
        formatted_results.append({
            "type": "text",
            "content": text,
            "box": box
        })
        log_text.append(f"[TEXT] {text}")

    Log.info("[Structure] ✅ Hoàn tất. Vùng nhận diện: {}. Thời gian: {:.2f}s".format(
        len(formatted_results), time.time() - start
    ))
    return formatted_results, log_text


# ============================================================
# Smart Menu OCR
# ============================================================

def smart_menu_ocr_extract(image_path, img=None):
    """
    Sử dụng OCR Box để gom nhóm các từ theo cùng một dòng (chứa tên món + giá),
    và tự động phân loại Category Title dựa vào độ cao của box chữ.
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
        line_boxes.sort(key=lambda b: b['x_min'])
        
        max_line_height = max(b['height'] for b in line_boxes)
        is_title = max_line_height >= title_height_threshold
        
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


# ============================================================
# Deprecated stubs (tương thích ngược)
# ============================================================

def filter_useless_lines(ocr_data):
    """[DEPRECATED] Không dùng."""
    return ocr_data


def filter_back_side_lines(ocr_data):
    """[DEPRECATED] Không dùng."""
    return ocr_data