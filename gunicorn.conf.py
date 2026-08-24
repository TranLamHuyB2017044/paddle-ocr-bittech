"""
Gunicorn lifecycle hooks.

Không load ONNX Runtime session trong master khi dùng --preload. Mỗi worker
khởi tạo MODNet/InsightFace sau fork để tránh chia sẻ native session không an toàn.
"""


def post_fork(server, worker):
    from src.models.model_loader import model_loader

    # Đóng kết nối kế thừa từ master process sau khi fork để tránh xung đột file descriptor/socket
    try:
        from src.database.mongo import client
        client.close()
    except Exception:
        pass

    try:
        from src.utils.redis_client import redis_conn
        redis_conn.connection_pool.disconnect()
    except Exception:
        pass

    worker.log.info("Preloading photo models for worker pid=%s", worker.pid)
    model_loader.preload_photo_models(require_rembg=True)
    worker.log.info("Photo models ready for worker pid=%s", worker.pid)
