"""
Gunicorn lifecycle hooks.
"""


def post_fork(server, worker):
    from src.shared.models.model_loader import model_loader

    worker.log.info("Preloading photo models for worker pid=%s", worker.pid)
    model_loader.preload_photo_models(require_rembg=True)
    worker.log.info("Photo models ready for worker pid=%s", worker.pid)
