# OCR & Legal Text Classification API

Dự án API tích hợp **PaddleOCR** (nhận diện văn bản tiếng Việt) và **Transformers** (phân loại văn bản pháp lý), sẵn sàng deploy lên Railway.

## 🚀 Hướng dẫn chạy nhanh (Local Development)

Làm theo các bước sau để chạy dự án trên máy tính của bạn.

### 1. Chuẩn bị môi trường

Yêu cầu: Python 3.10 trở lên.

**Bước 1: Tạo môi trường ảo (Virtual Environment)**

```bash
# Windows
python -m venv venv

# Linux/macOS
python3 -m venv venv
```

**Bước 2: Kích hoạt môi trường ảo**

```bash
# Windows (Command Prompt)
venv\Scripts\activate

# Windows (PowerShell)
venv\Scripts\Activate.ps1

# Linux/macOS
source venv/bin/activate
```

### 2. Cài đặt thư viện

Sau khi kích hoạt môi trường ảo, chạy lệnh sau để cài đặt các thư viện cần thiết:

```bash
pip install -r requirements.txt
```

> ⚠️ **Lưu ý:** Quá trình này có thể mất 5-10 phút do phải tải PyTorch và các thư viện Deep Learning nặng.

### 3. Chạy Server

```bash
python app.py
```

Server sẽ khởi động tại: `http://localhost:5000`

> **Lần chạy đầu tiên:** Hệ thống sẽ tự động tải model `protonx-models/protonx-legal-tc` và PaddleOCR models. Vui lòng kiên nhẫn đợi.

---

## 📖 Sử dụng API

### Tài liệu Swagger

Sau khi cài `requirements.txt` và chạy server:

- Swagger UI: [http://localhost:5000/api-doc/](http://localhost:5000/api-doc/)
- Đặc tả JSON: [http://localhost:5000/api-doc/swagger.json](http://localhost:5000/api-doc/swagger.json)

Khung hiện có tài liệu cho `GET /` và `GET /api/document/{doc_id}`.
Health check chỉ xác nhận ứng dụng đang chạy, không kiểm tra database/worker.
Với API OCR, bấm **Authorize** và nhập API key đầy đủ (`ak_ACCESS.SECRET`);
Swagger sẽ gửi header `x-api-key`. Có thể nhập `x-device-id` nếu cần.

Để bổ sung endpoint, tạo đặc tả Swagger 2.0 YAML trong `docs/api/<module>/`,
rồi thêm `@swag_from(str(DOCS_DIR / "<module>" / "<file>.yml"))` dưới decorator
xác thực và trên hàm xử lý. Import `swag_from` từ `flasgger` và `DOCS_DIR`
từ `src.core.swagger`. Các decorator bọc hàm cần giữ metadata bằng `functools.wraps`.
Chỉ các route `/` và `/api/…` có đặc tả mới xuất hiện trong tài liệu.

Kiểm tra khung tài liệu độc lập với model AI/database:

```bash
python -m unittest discover -s tests -p "test_swagger.py"
```

### Endpoint: `POST /api/detect`

Gửi file ảnh để nhận diện và phân loại văn bản.

**Request (cURL):**

```bash
curl -X POST http://localhost:5000/api/detect \
  -F "file=@path/to/your/image.jpg"
```

**Response (JSON):**

```json
{
  "success": true,
  "filename": "20231203_160000_image.jpg",
  "ocr_results": [
    {
      "original_text": "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",
      "ocr_confidence": 0.998,
      "classified_text": "QUỐC HIỆU TIÊU NGỮ",
      "classification_score": 0.985
    }
  ],
  "id_card_info": {
    "id_number": "001234567890",
    "full_name": "NGUYỄN VĂN A",
    "date_of_birth": "01/01/1990",
    ...
  }
}
```

---

## 🐳 Deploy lên Railway (Docker)

Dự án đã được cấu hình sẵn Dockerfile để deploy.

1. Đẩy code lên GitHub.
2. Tạo project mới trên [Railway](https://railway.app/).
3. Kết nối với repo GitHub của bạn.
4. Railway sẽ tự động detect Dockerfile và build.

**Lưu ý cấu hình Railway:**
- RAM: Tối thiểu 2GB (do chạy model AI).
- Timeout: Tăng lên 300s (5 phút) để tránh lỗi timeout khi tải model lần đầu.

---

## 📂 Cấu trúc dự án

- `app.py`: Server chính (Flask).
- `requirements.txt`: Các thư viện cần thiết.
- `Dockerfile`: Cấu hình build cho Railway.
- `uploads/`: Thư mục lưu ảnh tạm thời.


# Khởi động tất cả (API, Worker, Redis) chạy ngầm
docker-compose up -d --build
docker-compose up -d --force-recreate


# Xem log của API (Để kiểm tra lỗi request)
docker-compose logs -f

# Dừng hệ thống
docker-compose down

# Truy cập vào redis trong docker
docker exec -it paddle-ocr-redis redis-cli
# Kiểm tra số lượng job đang chờ
LLEN rq:queue:rag_tasks
# Xóa sạch hàng đợi (nếu muốn làm lại từ đầu)
FLUSHALL
