"""
File Utilities
Xử lý các thao tác liên quan đến file
"""
import os
from datetime import datetime
from cccd.config import ALLOWED_EXTENSIONS, UPLOAD_FOLDER


def allowed_file(filename):
    """
    Kiểm tra xem file có phải định dạng hợp lệ không
    
    Args:
        filename: Tên file cần kiểm tra
        
    Returns:
        bool: True nếu file hợp lệ, False nếu không
    """
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def save_uploaded_files(front_file, back_file):
    """
    Lưu các file upload với timestamp
    
    Args:
        front_file: File ảnh mặt trước
        back_file: File ảnh mặt sau
        
    Returns:
        tuple: (path_front, path_back)
    """
    # Tạo thư mục nếu chưa có
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    # Tạo timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Tạo đường dẫn
    path_front = os.path.join(UPLOAD_FOLDER, f"{timestamp}_front.jpg")
    path_back = os.path.join(UPLOAD_FOLDER, f"{timestamp}_back.jpg")
    
    # Lưu file
    front_file.save(path_front)
    back_file.save(path_back)
    
    return path_front, path_back
