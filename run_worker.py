import sys
import os
import threading
from rq import Worker, Queue
from src.utils.redis_client import redis_conn

# Thêm thư mục gốc vào path để các import hoạt động chính xác
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Định nghĩa các hàng đợi cần lắng nghe
listen = ['rag_tasks']

# Import tasks và pre-load models ngay khi worker khởi động
from src.models.model_loader import model_loader
model_loader.preload_all_models()
from src.tasks import document_tasks


def _run_retention_loop():
    """Chạy cleanup Cloudinary định kỳ; mặc định mỗi 6 giờ."""
    from src.tasks.retention_task import run_retention_cleanup, run_tts_cleanup
    from src.utils.logger import Log

    interval_seconds = max(
        3600,
        int(os.getenv("RETENTION_CLEANUP_INTERVAL_SECONDS", str(6 * 3600))),
    )
    stop_event = threading.Event()
    while not stop_event.is_set():
        try:
            run_retention_cleanup()
            run_tts_cleanup()
        except Exception as e:
            Log.error(f"[Retention-Loop] Cleanup cycle failed: {e}")
        stop_event.wait(interval_seconds)

if __name__ == '__main__':
    print("🚀 Worker starting...")
    print("👉 Giới hạn concurrency: 1 (Để tránh CPU spike 100%)")
    
    try:
        retention_thread = threading.Thread(
            target=_run_retention_loop,
            name="retention-cleanup",
            daemon=True,
        )
        retention_thread.start()

        # Sử dụng SimpleWorker (In-process) trên Windows để tránh tình trạng 
        # khởi tạo lại toàn bộ model (re-loading) cho mỗi task.
        from rq import SimpleWorker
        
        queues = [Queue(name, connection=redis_conn) for name in listen]
        
        # Tạo worker lắng nghe các queue này trong cùng 1 process
        worker = SimpleWorker(queues, connection=redis_conn)
        
        # Bắt đầu làm việc
        worker.work()
    except Exception as e:
        print(f"❌ Lỗi khi khởi động Worker: {e}")
        sys.exit(1)
