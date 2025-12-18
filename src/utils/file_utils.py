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
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_files(front_file=None, back_file=None):
    """
    Lưu các file upload với timestamp
    
    Args:
        front_file: File ảnh mặt trước (optional)
        back_file: File ảnh mặt sau (optional)
        
    Returns:
        tuple: (path_front, path_back) - Path có thể là None nếu không có file
    """
    # Tạo thư mục nếu chưa có
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    # Tạo timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    path_front = None
    path_back = None
    
    # Lưu file mặt trước nếu có
    if front_file:
        path_front = os.path.join(UPLOAD_FOLDER, f"{timestamp}_front.jpg")
        front_file.save(path_front)
        
    # Lưu file mặt sau nếu có
    if back_file:
        path_back = os.path.join(UPLOAD_FOLDER, f"{timestamp}_back.jpg")
        back_file.save(path_back)
    
    return path_front, path_back


def save_uploaded_file_list(files):
    """
    Lưu danh sách file upload
    
    Args:
        files: List các file objects
        
    Returns:
        list: Danh sách đường dẫn file đã lưu
    """
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    saved_paths = []
    
    for idx, file in enumerate(files):
        if file and allowed_file(file.filename):
            # Format: TIMESTAMP_index_filename
            filename = f"{timestamp}_{idx}_{file.filename}"
            path = os.path.join(UPLOAD_FOLDER, filename)
            file.save(path)
            saved_paths.append(path)
            
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
