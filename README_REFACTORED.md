# CCCD OCR - Refactored Structure

## 📁 Cấu trúc thư mục mới

```
paddle-ocr-bittech/
├── app.py                      # File cũ (backup)
├── app_new.py                  # File mới - Main Flask application
├── requirements.txt
├── Dockerfile
├── uploads/                    # Thư mục lưu ảnh upload
└── cccd/                       # Package chính cho CCCD OCR
    ├── __init__.py
    ├── config.py               # Cấu hình và constants
    │
    ├── models/                 # Package quản lý models
    │   ├── __init__.py
    │   └── model_loader.py     # Load và cache OCR & AI models
    │
    ├── utils/                  # Package các tiện ích
    │   ├── __init__.py
    │   ├── file_utils.py       # Xử lý file (validate, save)
    │   ├── ocr_utils.py        # OCR extraction và filtering
    │   └── text_cleaner.py     # Làm sạch text với AI model
    │
    ├── extractors/             # Package trích xuất thông tin
    │   ├── __init__.py
    │   ├── front_extractor.py  # Trích xuất mặt trước CCCD
    │   └── back_extractor.py   # Trích xuất mặt sau CCCD
    │
    └── api/                    # Package API routes
        ├── __init__.py
        └── routes.py           # Định nghĩa API endpoints
```

## 📦 Mô tả các module

### 1. `cccd/config.py`
- Chứa tất cả các cấu hình và constants
- Các từ khóa để filter và clean text
- Cấu hình OCR và AI model
- Giá trị mặc định

### 2. `cccd/models/model_loader.py`
- **ModelLoader class**: Singleton pattern để load và cache models
- Load PaddleOCR, tokenizer, và AI model
- Tự động detect GPU/CPU
- Đảm bảo models chỉ load 1 lần

### 3. `cccd/utils/file_utils.py`
- `allowed_file()`: Kiểm tra định dạng file
- `save_uploaded_files()`: Lưu file với timestamp

### 4. `cccd/utils/ocr_utils.py`
- `ocr_extract()`: Trích xuất text từ ảnh
- `filter_useless_lines()`: Lọc bỏ text không cần thiết

### 5. `cccd/utils/text_cleaner.py`
- `selective_clean_text_front()`: Clean text mặt trước (Họ tên, Quê quán, Địa chỉ)
- `selective_clean_text_back()`: Clean text mặt sau (chỉ ngày tháng)

### 6. `cccd/extractors/front_extractor.py`
- `extract_front()`: Trích xuất thông tin mặt trước
  - Số CCCD (9 hoặc 12 số)
  - Họ tên (3 chiến lược)
  - Ngày sinh
  - Giới tính
  - Quốc tịch
  - Quê quán
  - Địa chỉ thường trú
  - Ngày hết hạn

### 7. `cccd/extractors/back_extractor.py`
- `extract_back()`: Trích xuất thông tin mặt sau
  - Ngày cấp
  - Nơi cấp

### 8. `cccd/api/routes.py`
- `register_routes()`: Đăng ký routes cho Flask app
- `detect()`: API endpoint `/api/detect`
  - Validate request
  - Lưu file
  - OCR mặt trước/sau
  - Filter text
  - Clean text
  - Extract thông tin
  - Trả về kết quả + debug info

### 9. `app_new.py`
- Main Flask application
- Setup CORS
- Load models
- Register routes
- Run server

## 🚀 Cách sử dụng

### Chạy với file mới:
```bash
python app_new.py
```

### Hoặc đổi tên file:
```bash
# Backup file cũ
move app.py app_old.py

# Đổi tên file mới
move app_new.py app.py

# Chạy như bình thường
python app.py
```

## ✨ Lợi ích của cấu trúc mới

1. **Tách biệt rõ ràng**: Mỗi module có trách nhiệm riêng
2. **Dễ bảo trì**: Sửa lỗi hoặc thêm tính năng dễ dàng hơn
3. **Tái sử dụng**: Các hàm có thể import và sử dụng ở nhiều nơi
4. **Dễ test**: Có thể test từng module riêng biệt
5. **Mở rộng**: Dễ dàng thêm extractors mới cho các loại giấy tờ khác
6. **Clean code**: Code ngắn gọn, dễ đọc, dễ hiểu

## 🔄 Migration từ code cũ

Tất cả các hàm từ `app.py` cũ đã được tách ra thành:

| Hàm cũ | Module mới |
|--------|------------|
| `allowed_file()` | `cccd/utils/file_utils.py` |
| `ocr_extract()` | `cccd/utils/ocr_utils.py` |
| `filter_useless_lines()` | `cccd/utils/ocr_utils.py` |
| `selective_clean_text_back()` | `cccd/utils/text_cleaner.py` |
| `selective_clean_text_front()` | `cccd/utils/text_cleaner.py` |
| `extract_front()` | `cccd/extractors/front_extractor.py` |
| `extract_back()` | `cccd/extractors/back_extractor.py` |
| `clean_label()` | `cccd/extractors/front_extractor.py` |
| `detect()` API | `cccd/api/routes.py` |
| Model loading | `cccd/models/model_loader.py` |
| Constants | `cccd/config.py` |

## 📝 Notes

- File `app.py` cũ vẫn được giữ lại để backup
- Tất cả chức năng hoạt động giống hệt như trước
- Không có thay đổi về logic xử lý
- API endpoint vẫn là `/api/detect` với cùng request/response format
