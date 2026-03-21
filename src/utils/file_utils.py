"""
File Utilities
Xử lý các thao tác liên quan đến file
"""
import os
from datetime import datetime
from src.config import ALLOWED_EXTENSIONS, UPLOAD_FOLDER


def allowed_file(filename):
    """
    Kiểm tra xem file có phải định dạng hợp lệ không
    
    Args:
        filename: Tên file cần kiểm tra
        
    Returns:
        bool: True nếu file hợp lệ, False nếu không
    """
    if not filename or "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_EXTENSIONS



def save_uploaded_file(file):
    """
    Saves a single uploaded file.
    """
    if not file:
        return None
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ext = "jpg"
    if file.filename and "." in file.filename:
        ext = file.filename.rsplit(".", 1)[1].lower()
    
    path = os.path.join(UPLOAD_FOLDER, f"{timestamp}_{file.filename}")
    file.save(path)
    return path


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
    Lưu danh sách file upload
    """
    from src.utils.logger import Log
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    saved_paths = []
    
    Log.info(f"[Files] Incoming file list size: {len(files)}")
    
    for idx, file in enumerate(files):
        if not file:
            Log.warning(f"[Files] File at index {idx} is None/Empty")
            continue
            
        if allowed_file(file.filename):
            # Format: TIMESTAMP_index_filename
            filename = f"{timestamp}_{idx}_{file.filename}"
            path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(path)
            saved_paths.append(path)
            Log.info(f"[Files] ✅ Saved valid file: {file.filename}")
        else:
            Log.error(f"[Files] ❌ Rejected invalid extension: {file.filename}. Allowed: {ALLOWED_EXTENSIONS}")
            
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
