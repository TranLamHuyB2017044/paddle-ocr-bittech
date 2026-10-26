"""
Gunicorn lifecycle hooks.
"""


def post_fork(server, worker):
    from src.shared.models.model_loader import model_loader

    # Đóng kết nối kế thừa từ master process và khởi tạo kết nối mới riêng cho worker
    # để tránh xung đột file descriptor / socket giữa các tiến trình
    try:
        from src.core.database.mongo import close_mongo_client, init_mongo_client
        close_mongo_client()
        init_mongo_client(ping=False)
        worker.log.info("Initialized fresh MongoDB client for worker pid=%s", worker.pid)
    except Exception as e:
        worker.log.warning("Could not re-init worker mongo client: %s", e)

    try:
        from src.shared.utils.redis_client import redis_conn
        redis_conn.connection_pool.disconnect()
    except Exception as e:
        worker.log.warning("Could not disconnect master redis pool: %s", e)

    worker.log.info("Preloading photo models for worker pid=%s", worker.pid)
    model_loader.preload_photo_models(require_rembg=True)
    worker.log.info("Photo models ready for worker pid=%s", worker.pid)
