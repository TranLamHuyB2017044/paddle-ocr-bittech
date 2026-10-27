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

Tài liệu bao phủ các nhóm Auth, Users, Documents, OCR, Photos, TTS, Chatbot,
Public Chatbot, Categories, RAG, Records, Subscriptions, Admin, Integrations,
Products và Events, cùng health check. Các URL alias và HTTP method đều được liệt kê.
Health check chỉ xác nhận ứng dụng đang chạy, không kiểm tra database/worker.
Với API có xác thực, bấm **Authorize** → **ApiKeyAuth** và nhập API key đầy đủ (`ak_ACCESS.SECRET`);
Swagger sẽ gửi header `x-api-key`. Có thể nhập `x-device-id` nếu cần.
API chatbot công khai dùng **PublicTokenAuth** (`x-public-token`).
**GoogleBearerAuth** dành riêng cho thao tác lưu Sheets; nhập `Bearer <Google access token>`.

Các đặc tả Swagger 2.0 nằm trong `docs/api/modules/*.yml`, khóa là tên Flask endpoint
(ví dụ `file_bp.detect`, `tts.generate_speech`). `init_swagger(app)` gắn đặc tả sau khi
đăng ký Blueprint; khi thêm endpoint, bổ sung mục vào YAML của module tương ứng.
Mỗi module dùng một file, không cần tạo file cho từng endpoint. Khi thay đổi tham số
hoặc response trong hàm xử lý, cập nhật mục tương ứng trong YAML cùng lần sửa code.
Health check và trạng thái OCR vẫn dùng hai file YAML riêng qua `@swag_from`.
Không khai báo cùng endpoint bằng cả hai cách. Các decorator bọc hàm cần giữ metadata
bằng `functools.wraps`. Không bật validation request của Flasgger trong thay đổi này.

Swagger UI minh họa một kiểu request chính cho mỗi operation. Các API hỗ trợ cả JSON
và multipart có mô tả kiểu thay thế trong operation. Swagger 2.0 chỉ có bộ chọn một file
cho mỗi trường; gửi nhiều file bằng cách lặp lại khóa trong cURL/client:

```bash
curl -X POST http://localhost:5000/api/detect \
  -H "x-api-key: YOUR_API_KEY" \
  -F "type=idCard" \
  -F "files=@front.jpg" \
  -F "files=@back.jpg"
```

Đọc SSE bằng client hỗ trợ header; kết nối sẽ giữ mở đến khi ngắt:

```bash
curl -N http://localhost:5000/api/events -H "x-api-key: YOUR_API_KEY"
```

Hiện mã nguồn có hai cặp route trùng: `GET /api/admin/users` và
`POST /api/rag/documents/<document_id>/reindex`. Tài liệu dùng handler đăng ký đầu tiên,
đúng với Flask; chưa thay đổi logic/đăng ký route. Route phục vụ file tĩnh và upload
không nằm trong tài liệu API; `/send-email` được đưa vào nhóm Integrations.

Lưu ý hành vi hiện tại: middleware `require_role(0)` nhận số nguyên nhưng kiểm tra
quyền bằng phép `in`, nên tài khoản không phải admin có thể gặp HTTP 500 thay vì 403.
Các operation liên quan có ghi chú và response 500; lần cập nhật tài liệu này chưa sửa middleware.

Kiểm tra tài liệu độc lập với model AI/database (môi trường cần các thư viện phát triển):

```bash
pip install -r requirements-dev.txt
python -m unittest discover -s tests -p "test_swagger.py"
```

Bộ kiểm tra dựng URL map từ khai báo route thật, kiểm tra độ phủ URL/method,
xác thực, path parameters, upload/SSE, tài nguyên UI và chuẩn Swagger 2.0.
Các handler nghiệp vụ trong kiểm tra độ phủ được thay bằng stub để không gọi dịch vụ ngoài.

### Endpoint: `POST /api/detect`

Gửi ảnh hoặc `raw_text` để tạo tác vụ OCR bất đồng bộ.

**Request (cURL):**

```bash
curl -X POST http://localhost:5000/api/detect \
  -H "x-api-key: YOUR_API_KEY" \
  -F "type=idCard" \
  -F "files=@path/to/your/image.jpg"
```

**Response (HTTP 202):**

```json
{
  "statusCode": 202,
  "message": "Detection task enqueued",
  "data": {
    "document_id": "YOUR_DOCUMENT_ID"
  }
}
```

Lấy kết quả bằng `GET /api/document/YOUR_DOCUMENT_ID` với cùng header `x-api-key`,
hoặc theo dõi sự kiện ở `/api/events`.

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
