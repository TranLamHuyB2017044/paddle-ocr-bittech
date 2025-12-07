"""
Text Cleaner
Làm sạch text sử dụng AI model
"""
import time
from datetime import datetime
from cccd.models.model_loader import model_loader
from cccd.config import DATE_KEYWORDS, FRONT_KEYWORDS
from cccd.utils.logger import Log


def selective_clean_text_back(lines):
    """
    CHỈ clean text cho các dòng chứa ngày tháng (mặt sau)
    Các dòng khác giữ nguyên để tiết kiệm thời gian
    
    Args:
        lines: Danh sách các dòng text
        
    Returns:
        list: Danh sách các dòng text đã được làm sạch
    """
    start_time = time.time()
    Log.info(f"[CLEAN-SELECTIVE] 🎯 Làm sạch có chọn lọc (chỉ ngày tháng). Số dòng: {len(lines)}")
    
    # ⚠️ Kiểm tra input rỗng
    if len(lines) == 0:
        Log.warning(f"[CLEAN-SELECTIVE] ⚠️  CẢNH BÁO: Không có dòng text nào!")
        return []
    
    cleaned = []
    cleaned_count = 0
    skipped_count = 0
    
    for idx, line in enumerate(lines, 1):
        line_lower = line.lower()
        
        # Kiểm tra xem dòng này có chứa thông tin ngày tháng không
        needs_cleaning = any(keyword in line_lower for keyword in DATE_KEYWORDS)
        
        if needs_cleaning:
            # Clean dòng này
            Log.debug(f"[CLEAN-SELECTIVE] 🧹 Dòng {idx}/{len(lines)} - CẦN CLEAN. TRƯỚC: '{line[:60]}'")
            line_start = time.time()
            
            inputs = model_loader.tokenizer(
                line, 
                return_tensors="pt",
                truncation=True, 
                max_length=80
            ).to(model_loader.device)

            outputs = model_loader.model.generate(
                **inputs,
                max_new_tokens=80,
                num_beams=3,
                num_return_sequences=1,
                early_stopping=True,
                do_sample=False,
                length_penalty=1.0
            )

            cleaned_line = model_loader.tokenizer.decode(outputs[0], skip_special_tokens=True)
            cleaned.append(cleaned_line)
            cleaned_count += 1
            
            line_elapsed = time.time() - line_start
            Log.debug(f"[CLEAN-SELECTIVE]    📤 SAU:   '{cleaned_line[:60]}'. Thời gian: {line_elapsed:.2f}s")
        else:
            # Giữ nguyên dòng này

            Log.debug(f"[CLEAN-SELECTIVE] ⏭️  Dòng {idx}/{len(lines)} - BỎ QUA: '{line[:60]}'")
            cleaned.append(line)
            skipped_count += 1
    
    total_elapsed = time.time() - start_time
    
    # ⚠️ Tránh chia cho 0
    if len(lines) > 0:
        saving_pct = skipped_count / len(lines) * 100
        Log.info(f"[CLEAN-SELECTIVE] ✅ Hoàn thành. Clean: {cleaned_count}, Bỏ qua: {skipped_count}, Tiết kiệm: {saving_pct:.1f}%. Tổng thời gian: {total_elapsed:.2f}s")
    else:
        Log.warning(f"[CLEAN-SELECTIVE] ⚠️  Không có dòng nào để xử lý")
    
    return cleaned


def selective_clean_text_front(lines):
    """
    CHỈ clean text cho các dòng chứa Họ tên, Quê quán, Địa chỉ (mặt trước)
    Các dòng khác giữ nguyên để tiết kiệm thời gian
    
    Args:
        lines: Danh sách các dòng text
        
    Returns:
        list: Danh sách các dòng text đã được làm sạch
    """
    start_time = time.time()
    Log.info(f"[CLEAN-SELECTIVE-FRONT] 🎯 Làm sạch có chọn lọc (Họ tên, Quê quán, Địa chỉ). Số dòng: {len(lines)}")
    
    # ⚠️ Kiểm tra input rỗng
    if len(lines) == 0:
        Log.warning(f"[CLEAN-SELECTIVE-FRONT] ⚠️  CẢNH BÁO: Không có dòng text nào!")
        return []
    
    cleaned = []
    cleaned_count = 0
    skipped_count = 0
    
    for idx, line in enumerate(lines, 1):
        line_lower = line.lower()
        
        # Kiểm tra xem dòng này có chứa thông tin cần clean không
        needs_cleaning = any(keyword in line_lower for keyword in FRONT_KEYWORDS)
        
        # Ngoài ra, clean các dòng ALL CAPS (có thể là tên)
        if not needs_cleaning and line.strip().isupper() and len(line.strip()) > 3:
            needs_cleaning = True
        
        if needs_cleaning:
            # Clean dòng này

            Log.debug(f"[CLEAN-SELECTIVE-FRONT] 🧹 Dòng {idx}/{len(lines)} - CẦN CLEAN. TRƯỚC: '{line[:60]}'")
            line_start = time.time()
            
            inputs = model_loader.tokenizer(
                line, 
                return_tensors="pt",
                truncation=True, 
                max_length=80
            ).to(model_loader.device)

            outputs = model_loader.model.generate(
                **inputs,
                max_new_tokens=80,
                num_beams=3,
                num_return_sequences=1,
                early_stopping=True,
                do_sample=False,
                length_penalty=1.0
            )

            cleaned_line = model_loader.tokenizer.decode(outputs[0], skip_special_tokens=True)
            cleaned.append(cleaned_line)
            cleaned_count += 1
            
            line_elapsed = time.time() - line_start

            Log.debug(f"[CLEAN-SELECTIVE-FRONT]    📤 SAU:   '{cleaned_line[:60]}'. Thời gian: {line_elapsed:.2f}s")
        else:
            # Giữ nguyên dòng này
            Log.debug(f"[CLEAN-SELECTIVE-FRONT] ⏭️  Dòng {idx}/{len(lines)} - BỎ QUA: '{line[:60]}'")
            cleaned.append(line)
            skipped_count += 1
    
    total_elapsed = time.time() - start_time
    # ⚠️ Tránh chia cho 0
    if len(lines) > 0:
        saving_pct = skipped_count / len(lines) * 100
        Log.info(f"[CLEAN-SELECTIVE-FRONT] ✅ Hoàn thành. Clean: {cleaned_count}, Bỏ qua: {skipped_count}, Tiết kiệm: {saving_pct:.1f}%. Tổng thời gian: {total_elapsed:.2f}s")
    else:
        Log.warning(f"[CLEAN-SELECTIVE-FRONT] ⚠️  Không có dòng nào để xử lý")
    
    return cleaned
