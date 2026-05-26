# Hướng dẫn sử dụng API TTS bằng Postman

#BASE_URL=http://192.168.1.241:9000

## 1. Lấy danh sách giọng đọc mẫu

### Endpoint
```
GET /api/tts/voices
```

### Cấu hình trong Postman
1. Chọn phương thức **GET**
2. Nhập URL: `{{base_url}}/api/tts/voices`
3. Thêm header xác thực (nếu cần):
   - Key: `x-api-key`
   - Value: `ak_23c52aa924b249d5.d89c16fdd61a6219454acd032b2c2d6400f2bf71211dabe2815b36e0affadeab`
4. Nhấn **Send**

### Kết quả phản hồi
```json
{
  "statusCode": 200,
  "message": "Lấy danh sách giọng đọc mẫu thành công",
  "data": [
    {
      "voice_id": "voice_1",
      "description": "Giọng nữ miền Bắc"
    },
    {
      "voice_id": "voice_2",
      "description": "Giọng nam miền Nam"
    }
  ]
}
```

---

## 2. Chuyển đổi văn bản thành giọng nói

### Endpoint
```
POST /api/tts
```

### Cấu hình cơ bản
1. Chọn phương thức **POST**
2. Nhập URL: `{{base_url}}/api/tts`
3. Thêm header xác thực (nếu cần):
   - Key: `x-api-key`
   - Value: `ak_23c52aa924b249d5.d89c16fdd61a6219454acd032b2c2d6400f2bf71211dabe2815b36e0affadeab`
4. Chọn tab **Body** → Chọn **form-data**

### Tham số form-data
| Tham số | Bắt buộc | Mô tả |
|---------|----------|-------|
| `text`  | Có       | Văn bản cần chuyển đổi thành giọng nói |
| `voice_name` | Không | Tên giọng đọc mẫu (lấy từ endpoint 1) |
| `download` | Không | `true` để tải file xuống, `false` (mặc định) để phát trực tiếp |
| `json_response` | Không | `true` để nhận URL tải file, `false` (mặc định) để nhận file nhị phân |

---

### Ví dụ 1: Sử dụng giọng đọc mẫu
1. Thêm các trường vào form-data:
   - Key: `text` → Value: `Xin chào, đây là ví dụ sử dụng giọng đọc mẫu`
   - Key: `voice_name` → Value: `voice_1` (lấy từ endpoint 1)
2. Nhấn **Send**
3. Kết quả: Nhận file WAV hoặc URL tải file (tùy chọn `json_response`)

---

### Ví dụ 2: Nhân bản giọng từ file mẫu
1. Thêm các trường vào form-data:
   - Key: `text` → Value: `Xin chào, đây là ví dụ nhân bản giọng nói`
   - Key: `voice_sample` → Chọn **File** → Chọn file âm thanh mẫu của bạn
2. Nhấn **Send**
3. Kết quả: Nhận file WAV với giọng nói được nhân bản từ file mẫu

---

### Ví dụ 3: Nhận URL tải file (JSON response)
1. Thêm các trường vào form-data:
   - Key: `text` → Value: `Xin chào, đây là ví dụ nhận URL tải file`
   - Key: `voice_name` → Value: `voice_1`
   - Key: `json_response` → Value: `true`
2. Nhấn **Send**
3. Kết quả phản hồi:
```json
{
  "statusCode": 200,
  "message": "Tổng hợp giọng nói thành công",
  "data": {
    "url": "/uploads/tts/output_123.wav",
    "format": "wav"
  }
}
```

---

## Lưu ý
- Thay thế `{{base_url}}` bằng URL thực tế của API (ví dụ: `http://localhost:5000`)
- Thời gian chờ tối đa cho yêu cầu TTS là 120 giây
- File âm thanh mẫu sẽ được xóa tự động sau khi xử lý xong
