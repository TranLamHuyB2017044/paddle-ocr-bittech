import sys
import os
from rq import Worker, Queue
from src.utils.redis_client import redis_conn

# Thêm thư mục gốc vào path để các import hoạt động chính xác
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Định nghĩa các hàng đợi cần lắng nghe
listen = ['rag_tasks']

# Import tasks và pre-load models ngay khi worker khởi động
print("📦 Pre-loading models (PaddleOCR, AI Models)...")
from src.models.model_loader import model_loader
# Accessing the property triggers the load once and stays in RAM
_ = model_loader.ocr 
from src.tasks import document_tasks

if __name__ == '__main__':
    print("🚀 Worker starting...")
    print("👉 Giới hạn concurrency: 1 (Để tránh CPU spike 100%)")
    
    try:
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
