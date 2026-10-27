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
Public Chatbot, Categories, RAG, Records, Subscriptions, Integrations,
Products và Events, cùng health check. Tài liệu công khai loại các route `/admin/`,
handler chỉ dành cho admin nằm ngoài prefix này và tham số chỉ admin được dùng
trên các API dùng chung. Việc ẩn tài liệu không thay đổi route hoặc kiểm tra quyền.
Health check chỉ xác nhận ứng dụng đang chạy, không kiểm tra database/worker.
Với API có xác thực, bấm **Authorize** → **ApiKeyAuth** và nhập API key đầy đủ (`ak_ACCESS.SECRET`);
Swagger sẽ gửi header `x-api-key`. Có thể nhập `x-device-id` nếu cần.
API chatbot công khai dùng **PublicTokenAuth** (`x-public-token`).
Lưu Sheets và kết nối Google Drive đều cần `x-api-key`. Google account phải khớp
người đang đăng nhập; Google Bearer token tùy chọn không thay thế API key.

Các đặc tả Swagger 2.0 nằm trong `docs/api/modules/*.yml`, khóa là tên Flask endpoint
(ví dụ `file_bp.detect`, `tts.generate_speech`). `init_swagger(app)` gắn đặc tả sau khi
đăng ký Blueprint; khi thêm endpoint, bổ sung mục vào YAML của module tương ứng.
Mỗi module dùng một file, không cần tạo file cho từng endpoint. Khi thay đổi tham số
hoặc response trong hàm xử lý, cập nhật mục tương ứng trong YAML cùng lần sửa code.
Health check và trạng thái OCR vẫn dùng hai file YAML riêng qua `@swag_from`.
Không khai báo cùng endpoint bằng cả hai cách. Các decorator bọc hàm cần giữ metadata
bằng `functools.wraps`. Không bật validation request của Flasgger trong thay đổi này.
Endpoint nội bộ mới không có `/admin/` trong URL cần thêm vào `HIDDEN_API_ENDPOINTS`
trong `src/core/swagger.py`, hoặc đánh dấu `x-internal: true` trên mục YAML.
Các mục có tag `Admin` cũng được loại khỏi đặc tả JSON công khai.

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

Với các cặp route trùng, ví dụ `POST /api/rag/documents/<document_id>/reindex`,
tài liệu dùng handler đăng ký đầu tiên,
đúng với Flask; chưa thay đổi logic/đăng ký route. Route phục vụ file tĩnh và upload
không nằm trong tài liệu API; `/send-email` được đưa vào nhóm Integrations.

Kiểm tra tài liệu độc lập với model AI/database (môi trường cần các thư viện phát triển):

```bash
pip install -r requirements-dev.txt
python -m unittest discover -s tests -p "test_swagger*.py"
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

## Phân quyền và lưu ý khi triển khai bản vá

API key xác thực danh tính, không cấp quyền truy cập mọi tài nguyên. Quyền được đọc
từ user trong database ở mỗi request; user bị vô hiệu hóa hoặc role không hợp lệ trả 401.
Thiếu quyền trên endpoint/tài nguyên trả 403. Client không thể tự cấp quyền bằng
`role`, `account_id`, `workspace_id`, `farm_id`, email hoặc `isDev` trong request.

| Role | Quyền |
|---|---|
| 0 | Admin, quản lý liên kết farm và các API quản trị |
| 1 | Manager cũ, chỉ tạo member trong account mình |
| 2 | Member cũ, giữ tương thích dữ liệu hiện có |
| 4 | User thông thường; đăng ký công khai luôn dùng role này |

User chỉ quản lý chatbot/farm thuộc account mình. RAG Records yêu cầu quyền workspace
(chủ sở hữu, cùng account hoặc admin); cập nhật/xóa Qdrant được lọc cả workspace và document ID.
Sửa/báo cáo kết quả OCR và xuất Sheets kiểm tra chủ sở hữu document.

### Liên kết farm với account

Admin gán liên kết bằng `PUT /api/admin/farms/<farm_id>/account`, JSON:

```json
{"account_id": "MONGODB_ACCOUNT_ID"}
```

Request phải có `x-api-key` của admin. `GET` trên cùng URL xem liên kết;
`DELETE` thu hồi liên kết. Các API này không xuất hiện trong Swagger công khai.
Liên kết lưu trong collection `farm_accounts`, mỗi `farm_id` chỉ có một account.
User không được tự tạo/sửa liên kết. Farm chưa gán hoặc thuộc account khác trả 403
trên cả train, detect, update_embedding và delete. Admin vẫn có thể thao tác.

Trước khi mở lại API sản phẩm cho user, admin cần gán chính xác các farm hiện có.
Gán lại farm cho account khác đồng nghĩa chuyển quyền truy cập toàn bộ sản phẩm
đang có trong farm đó; không cần di chuyển dữ liệu Qdrant.

### Các thay đổi cần cập nhật client

- Google Drive connect và save-to-sheet bắt buộc `x-api-key`. Kết nối Google cũ
  chưa có `owner_user_id` phải kết nối lại qua Drive connect; không suy luận quyền từ email.
- API chuyển Excel chỉ nhận file upload; bỏ hoàn toàn `file_path` trên server.
  Auto-index yêu cầu workspace thuộc phạm vi được phép truy cập.
- URL upload thô `/uploads/...` chỉ cho admin. User lấy file OCR qua API có
  kiểm tra quyền `GET /api/files/<doc_id>/view` và URL đã ký.
- `isDev` không bỏ qua kiểm tra thiết bị. Role manager/member cần gửi device ID
  khi không thuộc nhóm API/account được miễn theo chính sách hiện tại.

Kiểm tra hồi quy bảo mật, dùng repository giả lập và Qdrant trong bộ nhớ:

```bash
python -m unittest discover -s tests -p "test_*.py"
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
