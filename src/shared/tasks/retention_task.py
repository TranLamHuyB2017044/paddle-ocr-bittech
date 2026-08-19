"""
Retention Task
Job xóa ảnh hết hạn khỏi Cloudinary và đánh dấu soft-delete trong DB.
Job xóa file TTS cũ để giải phóng dung lượng.

Cách chạy (thêm vào cron / RQ Scheduler):
    from src.tasks.retention_task import run_retention_cleanup, run_tts_cleanup
    run_retention_cleanup()
    run_tts_cleanup()

Hoặc thêm vào run_worker.py:
    from rq_scheduler import Scheduler
    scheduler.cron("0 3 * * *", func=run_retention_cleanup, timeout=300)
    scheduler.cron("0 * * * *", func=run_tts_cleanup, timeout=300)  # Chạy mỗi giờ
"""
import os
import time
from src.shared.utils.logger import Log
from src.shared.utils.cloudinary_utils import cloudinary_service
from src.modules.ocr.repositories.file_storage_repository import file_storage_repo
from src.modules.auth.repositories.audit_log_repository import audit_log_repo, AuditEvent
from src.core.config import TTS_FILE_RETENTION_HOURS, UPLOAD_FOLDER


def run_tts_cleanup() -> dict:
    """
    Xóa các file TTS cũ hơn TTS_FILE_RETENTION_HOURS để giải phóng dung lượng.
    
    Returns:
        dict: Thống kê số file đã xóa / lỗi.
    """
    Log.info("[Retention-TTS] 🔍 Starting TTS file cleanup job...")
    tts_folder = os.path.join(UPLOAD_FOLDER, 'tts')
    
    if not os.path.exists(tts_folder):
        Log.info("[Retention-TTS] TTS folder doesn't exist, nothing to clean up.")
        return {"total": 0, "deleted": 0, "errors": 0}
    
    stats = {"total": 0, "deleted": 0, "errors": 0}
    now = time.time()
    cutoff = now - (TTS_FILE_RETENTION_HOURS * 3600)
    
    for filename in os.listdir(tts_folder):
        filepath = os.path.join(tts_folder, filename)
        if os.path.isfile(filepath):
            stats["total"] += 1
            try:
                file_mtime = os.path.getmtime(filepath)
                if file_mtime < cutoff:
                    os.remove(filepath)
                    stats["deleted"] += 1
                    Log.info(f"[Retention-TTS] ✅ Deleted old TTS file: {filename}")
            except Exception as e:
                stats["errors"] += 1
                Log.error(f"[Retention-TTS] ❌ Failed to delete {filename}: {e}")
    
    Log.info(f"[Retention-TTS] ✅ Done. Stats: {stats}")
    return stats


def run_retention_cleanup() -> dict:
    """
    Quét tất cả record hết hạn trong file_storage, xóa trên Cloudinary,
    ghi audit log và đánh dấu soft-delete.

    Returns:
        dict: Thống kê số file đã xóa / lỗi.
    """
    Log.info("[Retention] 🔍 Starting retention cleanup job...")
    expired = file_storage_repo.find_expired()

    stats = {"total": len(expired), "deleted": 0, "errors": 0}
    Log.info(f"[Retention] Found {stats['total']} expired file(s).")

    for record in expired:
        public_id     = record.get("cloudinary_public_id")
        resource_type = record.get("resource_type", "image")
        record_id     = str(record["_id"])
        doc_id        = record.get("document_id")
        owner_id      = record.get("owner_user_id")

        if not public_id:
            Log.warning(f"[Retention] ⚠️ Record {record_id} missing public_id, skipping.")
            file_storage_repo.mark_deleted(record_id)
            continue

        try:
            ok = cloudinary_service.delete_image(public_id, resource_type=resource_type)
            if ok:
                file_storage_repo.mark_deleted(record_id)
                audit_log_repo.log_event(
                    event_type=AuditEvent.FILE_DELETED,
                    actor_user_id="system_retention_job",
                    actor_role=-1,
                    target_doc_id=doc_id,
                    target_file=public_id,
                    reason="Retention policy: file expired",
                    metadata={"record_id": record_id, "owner": owner_id},
                )
                stats["deleted"] += 1
                Log.info(f"[Retention] ✅ Deleted {public_id}")
            else:
                stats["errors"] += 1
                Log.error(f"[Retention] ❌ Failed to delete {public_id}")
        except Exception as e:
            stats["errors"] += 1
            Log.error(f"[Retention] ❌ Exception deleting {public_id}: {e}")

    Log.info(f"[Retention] ✅ Done. Stats: {stats}")
    return stats
