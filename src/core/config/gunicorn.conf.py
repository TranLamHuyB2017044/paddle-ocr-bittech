"""
Gunicorn lifecycle hooks.
"""


def post_fork(server, worker):
    from src.shared.models.model_loader import model_loader

    # Đóng kết nối kế thừa từ master process sau khi fork để tránh xung đột file descriptor/socket
    try:
        from src.core.database.mongo import client
        client.close()
    except Exception as e:
        worker.log.warning("Could not close master mongo client: %s", e)

    try:
        from src.shared.utils.redis_client import redis_conn
        redis_conn.connection_pool.disconnect()
    except Exception as e:
        worker.log.warning("Could not disconnect master redis pool: %s", e)

    worker.log.info("Preloading photo models for worker pid=%s", worker.pid)
    model_loader.preload_photo_models(require_rembg=True)
    worker.log.info("Photo models ready for worker pid=%s", worker.pid)
