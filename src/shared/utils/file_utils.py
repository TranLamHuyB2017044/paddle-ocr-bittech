"""
File Utilities
Xử lý các thao tác liên quan đến file
"""
import os
import io
from datetime import datetime
from src.core.config import ALLOWED_EXTENSIONS, ALLOWED_IMAGE_EXTENSIONS, UPLOAD_FOLDER


# ========== MIME TYPE SIGNATURES (Magic Bytes) ==========
# Map: extension -> (magic_bytes_offset, expected_prefix)
_MAGIC_SIGNATURES: dict[str, list[bytes]] = {
    # Images
    "png":  [b"\x89PNG\r\n\x1a\n"],
    "jpg":  [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "gif":  [b"GIF87a", b"GIF89a"],
    "webp": [b"RIFF"],           # RIFF????WEBP — kiểm tra thêm ở dưới
    # Documents
    "pdf":  [b"%PDF-"],
    # DOCX / XLSX / PPTX đều là ZIP: PK\x03\x04
    "docx": [b"PK\x03\x04"],
    "xlsx": [b"PK\x03\x04"],
    # DOC (OLE Compound): D0 CF 11 E0
    "doc":  [b"\xd0\xcf\x11\xe0"],
    # Markdown — plain text, không có magic bytes rõ ràng → bỏ qua magic check
    "md":   [],
}


def _read_header(file_obj, size: int = 16) -> bytes:
    """Đọc N bytes đầu của file rồi seek về 0."""
    file_obj.seek(0)
    header = file_obj.read(size)
    file_obj.seek(0)
    return header


def _check_magic(header: bytes, ext: str) -> bool:
    """
    So sánh header bytes với signature của extension.
    Trả về True nếu khớp (hoặc ext không có signature bắt buộc như 'md').
    """
    sigs = _MAGIC_SIGNATURES.get(ext)
    if sigs is None:
        # Extension không được định nghĩa → từ chối
        return False
    if not sigs:
        # md / plain-text: không check magic bytes → pass
        return True

    for sig in sigs:
        if header[: len(sig)] == sig:
            # Xử lý đặc biệt cho WebP: RIFF????WEBP
            if ext == "webp":
                return header[8:12] == b"WEBP"
            return True

    return False


def validate_file_mime_type(file_obj, filename: str) -> tuple[bool, str]:
    """
    Validate loại file thật dựa trên magic bytes (không chỉ dựa extension).
    Áp dụng cho tất cả loại file trong ALLOWED_EXTENSIONS.

    Args:
        file_obj: File-like object (Flask FileStorage hoặc bất kỳ IO stream nào).
        filename: Tên file gốc (dùng để xác định extension mong đợi).

    Returns:
        (is_valid: bool, reason: str)
    """
    if not filename or "." not in filename:
        return False, "Tên file không hợp lệ hoặc thiếu extension."

    ext = filename.rsplit(".", 1)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, f"Extension '.{ext}' không được phép. Hỗ trợ: {sorted(ALLOWED_EXTENSIONS)}"

    header = _read_header(file_obj, size=16)
    if not _check_magic(header, ext):
        return False, (
            f"Nội dung thực của file không khớp với extension '.{ext}'. "
            "Có thể file đã bị giả mạo extension."
        )

    # Validate sâu hơn cho ảnh bằng Pillow
    if ext in {"png", "jpg", "jpeg"}:
        try:
            file_obj.seek(0)
            from PIL import Image
            with Image.open(file_obj) as img:
                img.verify()  # Phát hiện file ảnh bị corrupt / giả mạo
            file_obj.seek(0)
        except Exception:
            file_obj.seek(0)
            return False, f"File ảnh '.{ext}' không thể đọc được hoặc bị hỏng."

    # Validate sâu hơn cho PDF bằng pymupdf (fitz)
    if ext == "pdf":
        try:
            file_obj.seek(0)
            import fitz  # pymupdf
            raw = file_obj.read()
            fitz.open(stream=raw, filetype="pdf")
            file_obj.seek(0)
        except Exception:
            file_obj.seek(0)
            return False, "File PDF không hợp lệ hoặc bị hỏng."

    file_obj.seek(0)
    return True, "OK"


def validate_image_file(file_obj, filename: str) -> tuple[bool, str]:
    """
    Validate file ảnh dùng cho avatar / upload ảnh.
    Dùng ALLOWED_IMAGE_EXTENSIONS từ config.

    Args:
        file_obj: File-like object.
        filename: Tên file gốc.

    Returns:
        (is_valid: bool, reason: str)
    """
    if not filename or "." not in filename:
        return False, "Tên file không hợp lệ hoặc thiếu extension."

    ext = filename.rsplit(".", 1)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        return False, (
            f"Extension '.{ext}' không được phép cho ảnh. "
            f"Hỗ trợ: {sorted(ALLOWED_IMAGE_EXTENSIONS)}"
        )

    header = _read_header(file_obj, size=16)
    if not _check_magic(header, ext):
        return False, (
            f"Nội dung thực của file không khớp với extension '.{ext}'. "
            "Có thể file đã bị giả mạo extension."
        )

    # Validate bằng Pillow
    try:
        file_obj.seek(0)
        from PIL import Image
        with Image.open(file_obj) as img:
            img.verify()
        file_obj.seek(0)
    except Exception:
        file_obj.seek(0)
        return False, f"File ảnh '.{ext}' không thể đọc được hoặc bị hỏng."

    file_obj.seek(0)
    return True, "OK"


# ========== LEGACY HELPERS (giữ tương thích ngược) ==========

def allowed_file(filename: str) -> bool:
    """
    Kiểm tra extension có trong ALLOWED_EXTENSIONS không.
    Lưu ý: chỉ kiểm tra extension, không validate MIME.
    Dùng validate_file_mime_type() để kiểm tra đầy đủ.
    """
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS


def save_uploaded_files(front_file=None, back_file=None):
    """
    Lưu các file upload với timestamp, giữ nguyên extension
    """
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    path_front = None
    path_back = None
    
    if front_file:
        ext = "jpg"
        if front_file.filename and "." in front_file.filename:
            ext = front_file.filename.rsplit(".", 1)[1].lower()
        
        path_front = os.path.join(UPLOAD_FOLDER, f"{timestamp}_front.{ext}")
        front_file.save(path_front)
        
    if back_file:
        ext = "jpg"
        if back_file.filename and "." in back_file.filename:
            ext = back_file.filename.rsplit(".", 1)[1].lower()
            
        path_back = os.path.join(UPLOAD_FOLDER, f"{timestamp}_back.{ext}")
        back_file.save(path_back)
    
    return path_front, path_back


def save_uploaded_file_list(files):
    """
    Lưu danh sách file upload — validate cả extension lẫn MIME type thật.
    """
    from src.shared.utils.logger import Log
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    saved_paths = []
    
    Log.info(f"[Files] Incoming file list size: {len(files)}")
    
    for idx, file in enumerate(files):
        if not file:
            Log.warning(f"[Files] File at index {idx} is None/Empty")
            continue
        
        is_valid, reason = validate_file_mime_type(file, file.filename)
        if is_valid:
            # Format: TIMESTAMP_index_filename
            filename = f"{timestamp}_{idx}_{file.filename}"
            path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(path)
            saved_paths.append(path)
            Log.info(f"[Files] ✅ Saved valid file: {file.filename}")
        else:
            Log.error(f"[Files] ❌ Rejected file: {file.filename} — {reason}")
            
    return saved_paths

def copy_to_permanent_storage(file_path):
    """
    Copy a file to permanent storage folder and return its relative URL/Path.
    """
    import shutil
    
    # Store in 'storage' folder in root (or where app runs)
    # We use a relative path assuming the app root is the working directory
    STORAGE_FOLDER = "storage"
    os.makedirs(STORAGE_FOLDER, exist_ok=True)
    
    if not file_path or not os.path.exists(file_path):
        return None
        
    filename = os.path.basename(file_path)
    dest_path = os.path.join(STORAGE_FOLDER, filename)
    shutil.copy2(file_path, dest_path)
    
    # Return relative path for URL usage
    return f"/storage/{filename}"

def calculate_files_hash(file_paths=None, raw_text=None):
    """
    Calculate a combined hash of all files and/or raw text.
    Used for caching processed results.
    """
    import hashlib
    
    if not file_paths and not raw_text:
        return None
        
    combined_hash = hashlib.md5()
    
    # 1. Add raw text to hash if provided
    if raw_text:
        combined_hash.update(raw_text.encode('utf-8'))
    
    # 2. Add files to hash
    if file_paths:
        # Sort paths to ensure consistent hash
        for path in file_paths:
            if os.path.exists(path):
                with open(path, "rb") as f:
                    for chunk in iter(lambda: f.read(4096), b""):
                        combined_hash.update(chunk)
                    
    return combined_hash.hexdigest()
