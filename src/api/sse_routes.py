from flask import Blueprint, Response, request, g
from src.utils.auth_middleware import require_auth
from src.utils.redis_client import redis_conn
import json
from src.utils.logger import Log

sse_bp = Blueprint('sse_bp', __name__)

@sse_bp.route('/api/events', methods=['GET'])
@require_auth
def stream_events():
    """
    Server-Sent Events (SSE) endpoint to notify user about background task statuses.
    Channel: sse_user_<user_id>
    """
    user_id = str(g.user_id)
    
    def event_stream():
        pubsub = redis_conn.pubsub()
        channel = f"sse_user_{user_id}"
        pubsub.subscribe(channel)
        
        Log.info(f"[SSE] User {user_id} connected to event stream")
        
        # Initial connection message
        yield f"data: {json.dumps({'type': 'connection', 'status': 'connected', 'user_id': user_id})}\n\n"
        
        try:
            while True:
                # Use a timeout to allow sending heartbeats
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=20.0)
                
                if message:
                    if message['type'] == 'message':
                        raw_data = message['data']
                        if isinstance(raw_data, bytes):
                            raw_data = raw_data.decode('utf-8')
                        
                        try:
                            payload = json.loads(raw_data)
                            event_name = payload.get('event', 'status_update')
                            event_data = payload.get('data', {})
                            
                            # Add timestamp if not present
                            if isinstance(event_data, dict) and 'timestamp' not in event_data:
                                import time
                                event_data['timestamp'] = time.time()
                                
                            # Properly formatted SSE: event + data
                            yield f"event: {event_name}\ndata: {json.dumps(event_data)}\n\n"
                        except Exception as e:
                            Log.error(f"[SSE] Failed to parse message for user {user_id}: {e}")
                            # Fallback for non-JSON or malformed messages
                            yield f"data: {raw_data}\n\n"
                else:
                    # Send a heartbeat (comment in SSE) every 20 seconds to keep connection alive
                    yield ": heartbeat\n\n"
                    
        except GeneratorExit:
            Log.info(f"[SSE] User {user_id} disconnected from stream")
        except Exception as e:
            Log.error(f"[SSE] Stream error for user {user_id}: {e}")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        finally:
            try:
                pubsub.unsubscribe(channel)
                pubsub.close()
            except:
                pass

    return Response(event_stream(), mimetype='text/event-stream')
