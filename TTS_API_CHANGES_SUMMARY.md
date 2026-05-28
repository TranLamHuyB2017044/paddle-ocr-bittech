# Tóm tắt thay đổi API TTS

## Tổng quan
Tài liệu này tóm tắt các thay đổi được thực hiện để tích hợp API TTS với dịch vụ lưu trữ tệp bên ngoài (https://files.bittechx.cloud).

---

## Các thay đổi đã thực hiện

### 1. Cấu hình (`src/config.py`)
Thêm các biến cấu hình mới để hỗ trợ API tệp bên ngoài:

```python
# ========== EXTERNAL FILES API CONFIG ==========
FILES_API_URL = os.getenv("FILES_API_URL", "https://files.bittechx.cloud")
FILES_API_UPLOAD_ENDPOINT = os.getenv("FILES_API_UPLOAD_ENDPOINT", "/api/files/upload")
FILES_API_SYSTEM_ID = os.getenv("FILES_API_SYSTEM_ID", "5efc2c21-b02e-4c8f-965b-1e01d7384a51")
FILES_API_USER_ID = os.getenv("FILES_API_USER_ID", "51202")
FILES_API_ALIAS = os.getenv("FILES_API_ALIAS", "home")
FILES_API_KEY = os.getenv("FILES_API_KEY", "client_ecad0526a48d4595a59fba330896feb3")
```

---

### 2. Biến môi trường (`.env`)
Cập nhật file `.env` với cấu hình mới:

```env
FILES_API_URL=https://files.bittechx.cloud
FILES_API_UPLOAD_ENDPOINT=/api/files/upload
FILES_API_SYSTEM_ID=5efc2c21-b02e-4c8f-965b-1e01d7384a51
FILES_API_USER_ID=51202
FILES_API_ALIAS=home
FILES_API_KEY=client_ecad0526a48d4595a59fba330896feb3
```

---

### 3. Tác vụ Worker TTS (`src/tasks/document_tasks.py`)
Sửa đổi hàm `process_tts_task` để:
- Tải file WAV đã tạo lên API bên ngoài
- Thêm header `x-api-key` để xác thực
- Thêm logging chi tiết cho yêu cầu và phản hồi
- Bao gồm phản hồi tải lên trong tin nhắn Redis

```python
def process_tts_task(tts_id, text, voice_sample_path=None, voice_name=None):
    """
    Tác vụ nền để xử lý tạo giọng nói từ văn bản trên worker.
    """
    from src.services.tts_service import tts_service
    from src.utils.redis_client import redis_conn
    from src.config import FILES_API_URL, FILES_API_UPLOAD_ENDPOINT, FILES_API_SYSTEM_ID, FILES_API_USER_ID, FILES_API_ALIAS, FILES_API_KEY
    from src.utils.logger import Log
    import json
    import requests
    import os
    import traceback
    
    try:
        Log.info(f"[Worker-TTS] Bắt đầu tạo TTS cho tác vụ {tts_id}")
        output_wav_path = tts_service.synthesize(
            text=text,
            voice_sample_path=voice_sample_path,
            voice_name=voice_name
        )
        
        # Upload file to external API
        Log.info(f"[Worker-TTS] Đang tải file lên API bên ngoài: {output_wav_path}")
        upload_url = f"{FILES_API_URL}{FILES_API_UPLOAD_ENDPOINT}"
        
        with open(output_wav_path, 'rb') as f:
            files = {
                'files': (os.path.basename(output_wav_path), f, 'audio/wav')
            }
            data = {
                'system_id': FILES_API_SYSTEM_ID,
                'user_id': FILES_API_USER_ID,
                'alias': FILES_API_ALIAS
            }
            headers = {
                'x-api-key': FILES_API_KEY
            }
            
            Log.info(f"[Worker-TTS] Gửi yêu cầu đến: {upload_url}")
            Log.info(f"[Worker-TTS] Headers: {headers}")
            
            response = requests.post(upload_url, files=files, data=data, headers=headers, timeout=30)
            
            Log.info(f"[Worker-TTS] Phản hồi từ API bên ngoài - Status Code: {response.status_code}")
            Log.info(f"[Worker-TTS] Phản hồi nội dung: {response.text}")
            
            response.raise_for_status()
            upload_response = response.json()
        
        # Phát hành kết quả thành công kèm phản hồi tải lên
        result = {
            "status": "success",
            "output_path": output_wav_path,
            "upload_response": upload_response
        }
        redis_conn.publish(f"tts_channel_{tts_id}", json.dumps(result))
        Log.info(f"[Worker-TTS] Completed TTS generation and upload for task {tts_id}")
    except requests.exceptions.RequestException as e:
        Log.error(f"[Worker-TTS] Lỗi kết nối API bên ngoài cho tác vụ {tts_id}: {e}")
        if hasattr(e, 'response') and e.response is not None:
            Log.error(f"[Worker-TTS] Nội dung phản hồi lỗi: {e.response.text}")
        result = {
            "status": "failed",
            "error": str(e)
        }
        redis_conn.publish(f"tts_channel_{tts_id}", json.dumps(result))
    except Exception as e:
        Log.error(f"[Worker-TTS] Failed TTS generation for task {tts_id}: {e}")
        Log.error(f"[Worker-TTS] Stack trace: {traceback.format_exc()}")
        result = {
            "status": "failed",
            "error": str(e)
        }
        redis_conn.publish(f"tts_channel_{tts_id}", json.dumps(result))
```

---

### 4. Route API TTS (`src/api/tts_routes.py`)
Cập nhật endpoint `generate_speech` để:
- Lấy toàn bộ payload từ Redis thay vì chỉ lấy một số trường
- Thêm logging cho payload nhận được
- Trả về phản hồi của API bên ngoài

```python
            if message:
                try:
                    payload = json.loads(message["data"])
                    Log.info(f"[API-TTS] Nhận payload từ Worker: {json.dumps(payload, ensure_ascii=False)}")
                    final_result = payload.copy()
                    break

        if not final_result:
            return jsonify({"statusCode": 504, "message": "Yêu cầu xử lý TTS bị quá hạn (timeout)."}), 504

        if final_result["status"] == "failed":
            return jsonify({"statusCode": 500, "message": final_result["error"]}), 500

        # 4. Trả về dữ liệu phản hồi từ API upload file
        return jsonify(final_result["upload_response"]), final_result["upload_response"].get("statusCode", 200)
```

---

## Sử dụng
API TTS hiện trả về toàn bộ phản hồi từ dịch vụ lưu trữ tệp bên ngoài, bao gồm:
- Siêu dữ liệu tệp (id, tên, đường dẫn, loại, v.v.)
- URL truy cập công khai
- Thông tin tệp khác

Ví dụ phản hồi:
```json
{
  "data": {
    "results": [
      {
        "success": true,
        "file": {
          "id": "55899",
          "name": "tts_123456.wav",
          "alias": "tts-123456-wav-abc123",
          "path": "...",
          "type": "FILE",
          "ext": "wav",
          "mimeType": "audio/wav",
          "sizeInBytes": "...",
          "accessType": "PRIVATE",
          "publicPath": "...",
          "parentId": "...",
          "clientId": "122",
          "createdAt": "...",
          "updatedAt": "..."
        },
        "originalName": "tts_123456.wav"
      }
    ],
    "summary": {
      "total": 1,
      "success": 1,
      "failed": 0
    }
  },
  "message": "Upload hoàn tất: 1 thành công, 0 thất bại",
  "status": "success",
  "statusCode": 201,
  "timestamp": "..."
}
```
