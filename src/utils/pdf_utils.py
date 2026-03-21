import os
try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

from src.utils.logger import Log

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
            page_text = page.get_text().strip()
            
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

    os.makedirs(temp_dir, exist_ok=True)
    image_paths = []
    
    try:
        doc = fitz.open(pdf_path)
        for page_num in range(len(doc)):
            page = doc[page_num]
            # Higher DPI for better OCR
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2)) 
            
            img_path = os.path.join(temp_dir, f"{os.path.basename(pdf_path)}_p{page_num}.jpg")
            pix.save(img_path)
            image_paths.append(img_path)
            
        doc.close()
    except Exception as e:
        Log.error(f"[PDF] ❌ Failed to convert PDF to images: {e}")
        
    return image_paths
def extract_text_with_bboxes_from_pdf(pdf_path):
    """
    Extract text with page, line number, and bbox using PyMuPDF.
    Returns: List of dicts [{"page": int, "line": int, "bbox": [x1, y1, x2, y2], "text": str}]
    """
    if fitz is None:
        Log.error("[PDF] ❌ PyMuPDF (fitz) is not installed.")
        return []

    results = []
    try:
        doc = fitz.open(pdf_path)
        for page_num, page in enumerate(doc):
            text_dict = page.get_text("dict")
            line_idx = 1
            for block in text_dict["blocks"]:
                if "lines" in block:
                    for line in block["lines"]:
                        line_text = ""
                        for span in line["spans"]:
                            line_text += span["text"]
                        
                        if line_text.strip():
                            results.append({
                                "page": page_num + 1,
                                "line": line_idx,
                                "bbox": list(line["bbox"]),
                                "text": line_text.strip()
                            })
                            line_idx += 1
        doc.close()
    except Exception as e:
        Log.error(f"[PDF] ❌ Error extracting text with bboxes: {e}")
    
    return results
