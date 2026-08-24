import os
import redis
from rq import Queue

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Redis connection
redis_conn = redis.from_url(REDIS_URL)

# RAG Queue
rag_queue = Queue("rag_tasks", connection=redis_conn)

def publish_event(user_id, event_type, data):
    """
    Publish an event to a user-specific Redis channel for SSE.
    Handles non-serializable objects like ObjectId and datetime.
    """
    import json
    from datetime import datetime
    from bson import ObjectId

    def json_serial(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, ObjectId):
            return str(obj)
        return str(obj) # Fallback

    if isinstance(data, dict) and "event" not in data:
        data["event"] = event_type

    channel = f"sse_user_{user_id}"
    message = {
        "event": event_type,
        "data": data
    }
    
    try:
        payload = json.dumps(message, default=json_serial)
        redis_conn.publish(channel, payload)
    except Exception as e:
        from src.shared.utils.logger import Log
        Log.error(f"[Redis] Failed to publish event: {e}")
