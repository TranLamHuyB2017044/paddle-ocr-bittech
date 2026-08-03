"""
Gunicorn lifecycle hooks.

Không load ONNX Runtime session trong master khi dùng --preload. Mỗi worker
khởi tạo MODNet/InsightFace sau fork để tránh chia sẻ native session không an toàn.
"""


def post_fork(server, worker):
    from src.models.model_loader import model_loader

    worker.log.info("Preloading photo models for worker pid=%s", worker.pid)
    model_loader.preload_photo_models(require_rembg=True)
    worker.log.info("Photo models ready for worker pid=%s", worker.pid)
