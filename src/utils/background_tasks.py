
import threading
import os
from src.utils.logger import Log
from src.utils.cloudinary_utils import cloudinary_service
from src.services.log_service import log_service

def run_background_upload_and_log(user_id, doc_type, file_paths, info, metadata=None, document_id=None):
    """
    Spawns a background thread to upload files to Cloudinary 
    and save logs to MongoDB, then cleans up temporary files.
    """
    def task():
        try:
            final_file_paths = file_paths
            
            # 1. Cloudinary Upload (If configured)
            if cloudinary_service.configured and file_paths:
                Log.info(f"[BG-TASK] ☁️ Uploading {len(file_paths)} files to Cloudinary...")
                upload_urls = []
                for f_path in file_paths:
                    if os.path.exists(f_path):
                        url = cloudinary_service.upload_image(f_path)
                        if url: upload_urls.append(url)
                
                if upload_urls:
                    final_file_paths = upload_urls
                    Log.info(f"[BG-TASK] ☁️ Upload complete. URLs: {len(upload_urls)}")

            # 2. Log to DB
            doc_id = log_service.save_logs(user_id, doc_type, final_file_paths, info, metadata=metadata, document_id=document_id)
            Log.info(f"[BG-TASK] 💾 Database logs saved. Doc ID: {doc_id}")

        except Exception as e:
            Log.error(f"[BG-TASK] ❌ Error in background task: {e}")
        
        finally:
            # 3. Cleanup local files
            if file_paths:
                for f_path in file_paths:
                    if f_path and os.path.exists(f_path) and not f_path.startswith("http"):
                        try:
                            os.remove(f_path)
                            Log.info(f"[BG-TASK] 🗑️ Cleanup deleted: {f_path}")
                        except Exception as cleanup_e:
                            Log.error(f"[BG-TASK] ⚠️ Cleanup failed for {f_path}: {cleanup_e}")

    # Start the thread
    thread = threading.Thread(target=task)
    thread.daemon = True # Allow app to exit even if thread is running
    thread.start()
    Log.info(f"[BG-TASK] 🚀 Background upload/log task started for user {user_id}")
