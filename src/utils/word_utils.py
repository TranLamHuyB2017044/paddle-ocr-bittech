import os
try:
    import aspose.words as aw
except ImportError:
    aw = None

try:
    import docx
except ImportError:
    docx = None

import os
from src.utils.logger import Log

def extract_text_from_word(file_path):
    """
    Trích xuất văn bản từ file .doc hoặc .docx.
    Sử dụng logic Hybrid: python-docx cho .docx và aspose-words cho .doc
    """
    ext = file_path.lower().split('.')[-1]
    full_text = ""

    # --- ƯU TIÊN 1: Dùng python-docx cho .docx (Nhẹ và ổn định) ---
    if ext == 'docx' and docx is not None:
        try:
            Log.info(f"[Word] 📄 Thử trích xuất .docx bằng python-docx: {file_path}")
            doc = docx.Document(file_path)
            full_text = "\n".join([para.text for para in doc.paragraphs])
            if full_text.strip():
                Log.info(f"[Word] ✅ Trích xuất thành công bằng python-docx ({len(full_text)} ký tự)")
                return full_text.strip()
        except Exception as e:
            Log.warning(f"[Word] ⚠️ python-docx thất bại, sẽ thử aspose: {e}")

    # --- ƯU TIÊN 2: Dùng aspose-words cho .doc hoặc khi python-docx thất bại ---
    if aw is not None:
        try:
            Log.info(f"[Word] 🔄 Thử trích xuất bằng aspose-words: {file_path}")
            doc = aw.Document(file_path)
            raw_text = doc.get_text()
            
            if raw_text:
                lines = raw_text.split('\n')
                clean_lines = []
                for line in lines:
                    if "Evaluation Only" in line or "Aspose.Words" in line:
                        continue
                    clean_line = "".join(c for c in line if ord(c) >= 32 or c in '\n\r\t')
                    if clean_line.strip():
                        clean_lines.append(clean_line)
                
            full_text = '\n'.join(clean_lines)
            if full_text.strip():
                Log.info(f"[Word] ✅ Trích xuất thành công bằng aspose-words ({len(full_text)} ký tự)")
                return full_text.strip()
        except Exception as e:
            Log.error(f"[Word] ❌ aspose-words lỗi khi lấy text trực tiếp: {e}")

    # --- ƯU TIÊN 3: PHƯƠNG ÁN CUỐI CÙNG - CHUYỂN SANG PDF VÀ OCR ---
    # Nếu đến đây vẫn chưa có text, có thể file Word chỉ chứa ảnh (Scanned doc)
    if aw is not None:
        try:
            Log.info(f"[Word] 🔄 File Word có thể là ảnh scan. Đang thử chuyển sang PDF để xử lý...")
            doc = aw.Document(file_path)
            temp_pdf = file_path.replace(f".{ext}", "_temp.pdf")
            doc.save(temp_pdf) # Chuyển Word sang PDF
            
            from src.utils.pdf_utils import extract_text_from_pdf, get_pdf_pages_as_images
            from src.utils.ocr_utils import ocr_extract
            
            # Thử lấy text từ PDF vừa tạo
            pdf_text = extract_text_from_pdf(temp_pdf)
            
            if not pdf_text.strip():
                Log.info(f"[Word] PDF chuyển đổi không có text. Tiến hành OCR từng trang...")
                # Nếu PDF không có text, dùng flow OCR PDF trang
                image_paths = get_pdf_pages_as_images(temp_pdf)
                ocr_texts = []
                for img_p in image_paths:
                    res, _ = ocr_extract(img_p)
                    if res:
                        page_text = "\n".join([line['text'] if isinstance(line, dict) else str(line) for line in res])
                        ocr_texts.append(page_text)
                    if os.path.exists(img_p): os.remove(img_p)
                
                pdf_text = "\n\n".join(ocr_texts)
            
            # Dọn dẹp file PDF tạm
            if os.path.exists(temp_pdf): os.remove(temp_pdf)
            
            if pdf_text.strip():
                Log.info(f"[Word] ✅ Trích xuất thành công bằng OCR Fallback ({len(pdf_text)} ký tự)")
                return pdf_text.strip()
                
        except Exception as e:
            Log.error(f"[Word] ❌ OCR Fallback thất bại: {e}")
    
    return ""
