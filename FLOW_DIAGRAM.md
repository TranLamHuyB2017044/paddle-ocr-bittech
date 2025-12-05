# CCCD OCR - Luồng xử lý (Flow Diagram)

## 📊 Luồng xử lý chính

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLIENT REQUEST                            │
│                   POST /api/detect                               │
│              (front_image, back_image)                           │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    1. VALIDATE REQUEST                           │
│              (cccd/utils/file_utils.py)                          │
│                                                                  │
│  • Kiểm tra file có tồn tại không                               │
│  • Kiểm tra định dạng file (png, jpg, jpeg)                     │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    2. LƯU FILE                                   │
│              (cccd/utils/file_utils.py)                          │
│                                                                  │
│  • Tạo timestamp                                                │
│  • Lưu file vào thư mục uploads/                                │
│  • Trả về đường dẫn file                                        │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    3. OCR EXTRACTION                             │
│              (cccd/utils/ocr_utils.py)                           │
│                                                                  │
│  ┌──────────────────┐          ┌──────────────────┐            │
│  │  Mặt trước       │          │  Mặt sau         │            │
│  │  ocr_extract()   │          │  ocr_extract()   │            │
│  └────────┬─────────┘          └────────┬─────────┘            │
│           │                              │                      │
│           ▼                              ▼                      │
│  • Sử dụng PaddleOCR                                            │
│  • Trả về list of text lines + confidence scores               │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    4. FILTER TEXT                                │
│              (cccd/utils/ocr_utils.py)                           │
│                                                                  │
│  • Lọc bỏ các dòng text chung không cần thiết                   │
│  • Sử dụng USELESS_KEYWORDS từ config                           │
│  • Giảm thiểu noise trong data                                  │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    5. CLEAN TEXT (AI)                            │
│              (cccd/utils/text_cleaner.py)                        │
│                                                                  │
│  ┌────────────────────────────┐  ┌──────────────────────────┐  │
│  │  Mặt trước                 │  │  Mặt sau                 │  │
│  │  selective_clean_text_     │  │  selective_clean_text_   │  │
│  │  front()                   │  │  back()                  │  │
│  └────────┬───────────────────┘  └────────┬─────────────────┘  │
│           │                                │                    │
│           ▼                                ▼                    │
│  • Clean Họ tên, Quê quán,      • Clean chỉ ngày tháng        │
│    Địa chỉ                                                      │
│  • Sử dụng AI model (protonx-legal-tc)                         │
│  • Tiết kiệm thời gian bằng selective cleaning                 │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    6. EXTRACT INFORMATION                        │
│              (cccd/extractors/)                                  │
│                                                                  │
│  ┌────────────────────────────┐  ┌──────────────────────────┐  │
│  │  Mặt trước                 │  │  Mặt sau                 │  │
│  │  extract_front()           │  │  extract_back()          │  │
│  └────────┬───────────────────┘  └────────┬─────────────────┘  │
│           │                                │                    │
│           ▼                                ▼                    │
│  • Số CCCD                       • Ngày cấp                    │
│  • Họ tên                        • Nơi cấp                     │
│  • Ngày sinh                                                    │
│  • Giới tính                                                    │
│  • Quốc tịch                                                    │
│  • Quê quán                                                     │
│  • Địa chỉ thường trú                                           │
│  • Ngày hết hạn                                                 │
└────────────────────────┬────────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                    7. RETURN RESPONSE                            │
│                                                                  │
│  {                                                               │
│    "statusCode": 200,                                           │
│    "message": "Success",                                        │
│    "data": {                                                    │
│      "idNumber": "...",                                         │
│      "fullName": "...",                                         │
│      "dob": "...",                                              │
│      ...                                                        │
│    },                                                           │
│    "debug": {                                                   │
│      "total_time": "...",                                       │
│      "ocr_time": "...",                                         │
│      ...                                                        │
│    }                                                            │
│  }                                                              │
└─────────────────────────────────────────────────────────────────┘
```

## 🏗️ Kiến trúc module

```
┌─────────────────────────────────────────────────────────────────┐
│                         app_new.py                               │
│                      (Main Flask App)                            │
└────────────┬────────────────────────────────────────────────────┘
             │
             │ imports
             │
             ▼
┌─────────────────────────────────────────────────────────────────┐
│                        cccd/ package                             │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   config.py  │  │   models/    │  │    utils/    │          │
│  │              │  │              │  │              │          │
│  │ • Constants  │  │ • model_     │  │ • file_utils │          │
│  │ • Keywords   │  │   loader.py  │  │ • ocr_utils  │          │
│  │ • Defaults   │  │              │  │ • text_      │          │
│  │              │  │ (Singleton)  │  │   cleaner    │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                  │
│  ┌──────────────┐  ┌──────────────────────────────────┐        │
│  │ extractors/  │  │           api/                   │        │
│  │              │  │                                  │        │
│  │ • front_     │  │ • routes.py                      │        │
│  │   extractor  │  │   - register_routes()            │        │
│  │ • back_      │  │   - detect() endpoint            │        │
│  │   extractor  │  │                                  │        │
│  └──────────────┘  └──────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────┘
```

## 🔄 Dependencies giữa các module

```
app_new.py
    │
    ├─→ cccd.config (UPLOAD_FOLDER)
    ├─→ cccd.api.routes (register_routes)
    └─→ cccd.models.model_loader (model_loader)

cccd/api/routes.py
    │
    ├─→ cccd.utils.file_utils (allowed_file, save_uploaded_files)
    ├─→ cccd.utils.ocr_utils (ocr_extract, filter_useless_lines)
    ├─→ cccd.utils.text_cleaner (selective_clean_text_front, selective_clean_text_back)
    ├─→ cccd.extractors.front_extractor (extract_front)
    └─→ cccd.extractors.back_extractor (extract_back)

cccd/utils/ocr_utils.py
    │
    ├─→ cccd.models.model_loader (model_loader.ocr)
    └─→ cccd.config (USELESS_KEYWORDS)

cccd/utils/text_cleaner.py
    │
    ├─→ cccd.models.model_loader (model_loader.tokenizer, model_loader.model, model_loader.device)
    └─→ cccd.config (DATE_KEYWORDS, FRONT_KEYWORDS)

cccd/extractors/front_extractor.py
    │
    └─→ cccd.config (DEFAULT_NATIONALITY, ADDRESS_KEYWORDS, EXPIRY_LABEL_KEYWORDS, HOMETOWN_KEYWORDS)

cccd/extractors/back_extractor.py
    │
    └─→ cccd.config (DEFAULT_PLACE_OF_ISSUE)

cccd/models/model_loader.py
    │
    └─→ cccd.config (MODEL_PATH, OCR_CONFIG)
```

## 💡 Ưu điểm của kiến trúc này

1. **Separation of Concerns**: Mỗi module có trách nhiệm riêng biệt
2. **Single Responsibility**: Mỗi file chỉ làm một việc cụ thể
3. **DRY (Don't Repeat Yourself)**: Không lặp lại code
4. **Easy to Test**: Có thể test từng module độc lập
5. **Easy to Maintain**: Sửa lỗi dễ dàng, không ảnh hưởng module khác
6. **Easy to Extend**: Thêm tính năng mới không cần sửa code cũ
7. **Reusable**: Các hàm có thể tái sử dụng ở nhiều nơi
8. **Clean Code**: Code rõ ràng, dễ đọc, dễ hiểu
