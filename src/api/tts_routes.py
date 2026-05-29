import os
from flask import Blueprint, request, jsonify
from flask_limiter.util import get_remote_address
from werkzeug.utils import secure_filename
from src.utils.auth_middleware import require_auth
from src.utils.logger import Log
from src.services.tts_service import tts_service
from src.utils.rate_limit import limiter
from src.config import BASE_URL

tts_bp = Blueprint("tts", __name__)


@tts_bp.errorhandler(429)
def _tts_rate_limit_handler(e):
    """Trả về JSON 429 thống nhất với format lỗi của dự án."""
    Log.warning(f"[TTS Rate Limit] IP {get_remote_address()} bị chặn: {e.description}")
    return jsonify({
        "statusCode": 429,
        "message": "Quá nhiều yêu cầu. Vui lòng thử lại sau."
    }), 429


@tts_bp.route("/api/tts/voices", methods=["GET"])
@require_auth
@limiter.limit("30 per minute")
def get_preset_voices():
    """
    API endpoint lấy danh sách giọng đọc mẫu (preset voices) của VieNeu-TTS.
    """
    try:
        voices = tts_service.list_preset_voices()
        data = [{"voice_id": v_id, "description": desc} for desc, v_id in voices]
        return jsonify({
            "statusCode": 200,
            "message": "Lấy danh sách giọng đọc mẫu thành công",
            "data": data
        }), 200
    except Exception as e:
        Log.error(f"[TTS API] Lấy danh sách preset voices: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@tts_bp.route("/api/tts", methods=["POST"])
@require_auth
@limiter.limit("5 per minute")
@limiter.limit("20 per hour")
def generate_speech():
    """
    API endpoint chuyển đổi văn bản thành giọng nói sử dụng VieNeu-TTS.
    Hỗ trợ nhân bản giọng nói tức thì (Zero-shot Cloning) qua đính kèm file 'voice_sample'
    hoặc sử dụng giọng đọc mẫu có sẵn qua tham số 'voice_name'.
    """
    temp_voice_path = None
    try:
        # 1. Thu thập và kiểm tra văn bản đầu vào
        text = request.form.get("text", "").strip()
        if not text:
            return jsonify({"statusCode": 400, "message": "Thiếu tham số 'text' trong yêu cầu."}), 400

        voice_name = request.form.get("voice_name", "").strip() or None

        # 2. Kiểm tra file âm thanh ghi âm giọng mẫu tải lên (tùy chọn)
        voice_file = request.files.get("voice_sample")
        if voice_file and voice_file.filename:
            from src.config import UPLOAD_FOLDER
            temp_dir = os.path.join(UPLOAD_FOLDER, 'temp_voice')
            os.makedirs(temp_dir, exist_ok=True)
            
            filename = secure_filename(voice_file.filename)
            temp_voice_path = os.path.join(temp_dir, f"ref_{os.urandom(4).hex()}_{filename}")
            Log.info(f"💾 Đang lưu file ghi âm mẫu tạm thời vào: {temp_voice_path}")
            voice_file.save(temp_voice_path)

        # 3. Gọi service thực hiện tổng hợp giọng nói VieNeu-TTS qua Worker
        import uuid
        import json
        import time
        from src.utils.redis_client import rag_queue, redis_conn
        from src.tasks.document_tasks import process_tts_task

        tts_id = uuid.uuid4().hex
        
        # Đăng ký lắng nghe kênh Redis của task tts_id trước khi enqueue
        pubsub = redis_conn.pubsub()
        channel = f"tts_channel_{tts_id}"
        pubsub.subscribe(channel)

        Log.info(f"[API-TTS] Đang đẩy task TTS {tts_id} vào worker queue...")
        rag_queue.enqueue(
            process_tts_task,
            args=(tts_id, text),
            kwargs={
                "voice_sample_path": temp_voice_path,
                "voice_name": voice_name
            },
            job_timeout='3m'
        )

        # Chờ kết quả từ Worker
        wait_timeout = 180  
        start_wait = time.time()
        final_result = None

        while time.time() - start_wait < wait_timeout:
            message = pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=1.0
            )
            if message:
                try:
                    payload = json.loads(message["data"])
                    Log.info(f"[API-TTS] Nhận payload từ Worker: {json.dumps(payload, ensure_ascii=False)}")
                    final_result = payload.copy()
                    break
                except Exception as ex:
                    Log.error(f"[API-TTS] Lỗi phân giải kết quả từ Redis: {ex}")
            time.sleep(0.1)

        pubsub.unsubscribe(channel)
        pubsub.close()

        if not final_result:
            return jsonify({"statusCode": 504, "message": "Yêu cầu xử lý TTS bị quá hạn (timeout)."}), 504

        if final_result["status"] == "failed":
            return jsonify({"statusCode": 500, "message": final_result["error"]}), 500

        # 4. Trả về dữ liệu phản hồi từ API upload file
        return jsonify(final_result["upload_response"]), final_result["upload_response"].get("statusCode", 200)

    except Exception as e:
        Log.error(f"[TTS API] Lỗi xử lý API: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500
        
    finally:
        # Tiến hành xóa dọn dẹp file ghi âm mẫu tạm thời ngay lập tức để tránh làm đầy ổ cứng
        if temp_voice_path and os.path.exists(temp_voice_path):
            try:
                os.remove(temp_voice_path)
                Log.info(f"🗑️ Đã xóa file ghi âm tạm: {temp_voice_path}")
            except Exception as ex:
                Log.error(f"⚠️ Thất bại khi xóa file ghi âm tạm: {ex}")
