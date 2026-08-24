import os
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

from src.shared.utils.logger import Log

def is_pdf_scanned(pdf_path):
    """
    Kiểm tra xem file PDF là dạng scan (ảnh) hay dạng text.
    Trả về: True nếu là file scan, False nếu có chứa text.
    """
    if fitz is None:
        return True # Default to scan if library missing
        
    try:
        doc = fitz.open(pdf_path)
        # Kiểm tra 3 trang đầu tiên (thường đủ để kết luận)
        check_pages = min(len(doc), 3)
        
        for i in range(check_pages):
            page = doc[i]
            # 1. Thử lấy text
            text = page.get_text().strip()
            if text:
                # Nếu có text, đây là PDF Native (Text-based)
                doc.close()
                return False
                
        # Nếu duyệt qua các trang mà không có text nào
        doc.close()
        return True
    except Exception as e:
        Log.error(f"[PDF-CHECK] Lỗi khi kiểm tra file: {e}")
        return True

def extract_page_text_with_tables(page) -> str:
    """
    Trích xuất text từ page của PyMuPDF, định dạng các bảng biểu thành Markdown
    để giữ nguyên cấu trúc hàng/cột phục vụ cho RAG.
    """
    page_text = page.get_text().strip()
    if not page_text:
        return ""
        
    try:
        tables = page.find_tables()
        if not tables:
            return page_text
            
        table_bboxes = [t.bbox for t in tables]
        elements = []
        
        # 1. Trích xuất các block text thông thường nằm ngoài bảng
        blocks = page.get_text("blocks")
        for b in blocks:
            x0, y0, x1, y1, text, block_no, block_type = b
            in_table = False
            for bbox in table_bboxes:
                # Kiểm tra giao nhau giữa text block và bảng
                if not (x1 < bbox[0] or x0 > bbox[2] or y1 < bbox[1] or y0 > bbox[3]):
                    in_table = True
                    break
            if not in_table and text.strip():
                elements.append((y0, "text", text.strip()))
        
        # 2. Trích xuất các bảng dưới dạng Markdown
        for t in tables:
            grid = t.extract()
            md_lines = []
            if grid:
                # Tiêu đề cột
                headers = [str(cell or "").strip().replace("\n", " ") for cell in grid[0]]
                md_lines.append("| " + " | ".join(headers) + " |")
                md_lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
                # Các dòng dữ liệu
                for row in grid[1:]:
                    cells = [str(cell or "").strip().replace("\n", " ") for cell in row]
                    md_lines.append("| " + " | ".join(cells) + " |")
            md_table = "\n".join(md_lines)
            elements.append((t.bbox[1], "table", md_table))
            
        # 3. Sắp xếp các đoạn text và bảng theo thứ tự từ trên xuống dưới (y0)
        elements.sort(key=lambda x: x[0])
        return "\n\n".join([el[2] for el in elements])
        
    except Exception as e:
        Log.warning(f"[PDF-TABLES] Lỗi tự động nhận diện bảng: {e}")
        return page_text

def extract_text_from_pdf(pdf_path):
    """
    Extract text from PDF pages.
    Returns: List of dicts [{"text": str, "page_num": int}]
    """
    if fitz is None:
        Log.error("[PDF] ❌ PyMuPDF (fitz) is not installed. Cannot process PDF properly.")
        return []

    pages = []
    
    try:
        doc = fitz.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc[page_num]
            page_text = extract_page_text_with_tables(page)
            
            if page_text:
                pages.append({
                    "text": page_text,
                    "page_num": page_num + 1
                })
            else:
                Log.info(f"[PDF] Page {page_num + 1} appears to be scanned/image-based.")
                # We still add the page even if empty text, so OCR can fill it later if needed
                # But here we just return what we found.
                pages.append({
                    "text": "",
                    "page_num": page_num + 1
                })
                
        doc.close()
    except Exception as e:
        Log.error(f"[PDF] ❌ Failed to extract PDF: {e}")
        
    return pages

def get_pdf_pages_as_images(pdf_path, temp_dir="uploads/temp"):
    """
    Convert PDF pages to images for OCR.
    """
    if fitz is None:
        Log.error("[PDF] ❌ PyMuPDF (fitz) is not installed.")
        return []

    # Use absolute path to avoid permission issues when run from different contexts
    from src.core.config import root_dir
    abs_temp_dir = os.path.join(root_dir, temp_dir)
    os.makedirs(abs_temp_dir, exist_ok=True)
    image_paths = []
    
    import uuid
    try:
        doc = fitz.open(pdf_path)
        safe_base_name = str(uuid.uuid4())
        for page_num in range(len(doc)):
            page = doc[page_num]
            # Higher DPI for better OCR
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) 
            
            # Use a safe UUID filename to avoid Unicode path errors in fitz.save()
            img_path = os.path.join(abs_temp_dir, f"{safe_base_name}_p{page_num}.jpg")
            pix.save(img_path)
            image_paths.append(img_path)
            
        doc.close()
    except Exception as e:
        Log.error(f"[PDF] ❌ Failed to convert PDF to images: {e}")
        
    return image_paths
