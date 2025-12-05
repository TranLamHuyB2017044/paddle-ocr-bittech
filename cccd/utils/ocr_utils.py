"""
OCR Utilities
Các hàm tiện ích cho OCR extraction
"""
import time
from datetime import datetime
from cccd.models.model_loader import model_loader


def ocr_extract(image_path):
    """
    Trích xuất text từ ảnh sử dụng OCR
    
    Args:
        image_path: Đường dẫn đến file ảnh
        
    Returns:
        tuple: (list of text lines, list of confidence scores)
    """
    start_time = time.time()
    print(f"\n{'='*60}")
    print(f"[OCR] 🔍 Bắt đầu OCR: {image_path}")
    print(f"[OCR] ⏰ Thời gian: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
    
    # Sử dụng OCR từ model_loader
    result = model_loader.ocr.predict(image_path)
    
    for block in result:
        elapsed = time.time() - start_time
        num_lines = len(block["rec_texts"])
        print(f"[OCR] ✅ Hoàn thành OCR")
        print(f"[OCR] 📝 Số dòng text: {num_lines}")
        print(f"[OCR] ⏱️  Thời gian: {elapsed:.2f}s")
        
        # 📋 LOG CHI TIẾT: Hiển thị từng dòng text + confidence
        print(f"\n{'─'*60}")
        print(f"[OCR] 📋 CHI TIẾT TEXT DETECT:")
        print(f"{'─'*60}")
        for i, (text, score) in enumerate(zip(block["rec_texts"], block["rec_scores"]), 1):
            confidence = score * 100
            emoji = "✅" if confidence >= 80 else "⚠️" if confidence >= 60 else "❌"
            print(f"[OCR] {emoji} [{i:2d}] [{confidence:5.1f}%] {text[:70]}")
        print(f"{'─'*60}\n")
        
        print(f"{'='*60}\n")
        return block["rec_texts"], block["rec_scores"]
    
    print(f"[OCR] ⚠️  Không tìm thấy text")
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
    
    print(f"\n{'='*60}")
    print(f"[FILTER] 🗑️  Bắt đầu lọc text không cần thiết")
    print(f"[FILTER] 📝 Số dòng ban đầu: {len(lines)}")
    
    # ⚠️ Kiểm tra input rỗng
    if len(lines) == 0:
        print(f"[FILTER] ⚠️  CẢNH BÁO: Không có dòng text nào từ OCR!")
        print(f"{'='*60}\n")
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
            print(f"[FILTER] ❌ Loại bỏ (từ khóa '{matched_keyword}'): '{line[:60]}'")
        else:
            filtered.append(line)
            print(f"[FILTER] ✅ Giữ lại: '{line[:60]}'")
    
    print(f"\n[FILTER] 📊 Kết quả:")
    print(f"[FILTER]    Đã loại bỏ: {removed_count} dòng")
    print(f"[FILTER]    Còn lại: {len(filtered)} dòng")
    print(f"{'='*60}\n")
    
    return filtered
