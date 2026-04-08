from flask import Blueprint, Response, request, g, stream_with_context
from src.utils.auth_middleware import require_auth
from src.utils.redis_client import redis_conn
import json
import time
from src.utils.logger import Log

sse_bp = Blueprint('sse_bp', __name__)

@sse_bp.route('/api/events', methods=['GET'])
@require_auth
def stream_events():
    """
    Server-Sent Events (SSE) endpoint to notify user about background task statuses.
    Channel: sse_user_<user_id>

    Headers quan trọng:
      - X-Accel-Buffering: no  → Tắt Nginx buffer, client nhận event ngay lập tức
      - Cache-Control: no-cache → Không cache
      - Connection: keep-alive  → Giữ kết nối dài
    """
    user_id = str(g.user_id)

    def event_stream():
        pubsub = redis_conn.pubsub()
        channel = f"sse_user_{user_id}"
        pubsub.subscribe(channel)

        Log.info(f"[SSE] User {user_id} connected to event stream")

        # Gửi event connection ngay khi client kết nối thành công
        yield f"data: {json.dumps({'type': 'connection', 'status': 'connected', 'user_id': user_id})}\n\n"

        try:
            while True:
                # Timeout 5s: nếu không có message -> gửi heartbeat giữ connection
                # Giảm xuống 5s để tránh Nginx/Proxy ngắt kết nối khi chưa có dữ liệu ngay (Timeout 15s trước đây quá sát nút)
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=5.0)

                if message:
                    if message['type'] == 'message':
                        raw_data = message['data']
                        if isinstance(raw_data, bytes):
                            raw_data = raw_data.decode('utf-8')

                        try:
                            payload = json.loads(raw_data)
                            event_name = payload.get('event', 'status_update')
                            event_data = payload.get('data', {})

                            # Inject timestamp nếu chưa có
                            if isinstance(event_data, dict) and 'timestamp' not in event_data:
                                event_data['timestamp'] = time.time()

                            # SSE format chuẩn: event line + data line
                            yield f"event: {event_name}\ndata: {json.dumps(event_data)}\n\n"

                        except Exception as e:
                            Log.error(f"[SSE] Parse error for user {user_id}: {e}")
                            yield f"data: {raw_data}\n\n"
                else:
                    # Heartbeat mỗi 5s để:
                    # 1. Nginx/proxy biết connection còn sống
                    # 2. Flutter/Browser client không timeout
                    yield ": heartbeat\n\n"

        except GeneratorExit:
            # Client chủ động disconnect (bình thường)
            Log.info(f"[SSE] User {user_id} disconnected from stream")
        except Exception as e:
            Log.error(f"[SSE] Stream error for user {user_id}: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            try:
                pubsub.unsubscribe(channel)
                pubsub.close()
            except Exception:
                pass

    response = Response(
        stream_with_context(event_stream()),  # Giữ Flask app context trong generator
        mimetype='text/event-stream'
    )

    # ===== Headers bắt buộc cho SSE qua Nginx/AAPanel =====
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    response.headers['X-Accel-Buffering'] = 'no'   # ← Quan trọng nhất: tắt Nginx buffer
    response.headers['Connection'] = 'keep-alive'

    return response
