"""
Background Tasks
Xử lý bất đồng bộ sau khi OCR hoàn thành:

1. Ảnh OCR (jpg/jpeg/png/gif/webp):
   - Nếu workspace/user bật allow_source_file_storage → upload lên Cloudinary private.
   - Luôn xóa file tạm sau xử lý.

2. Non-image files (pdf, docx, doc, md):
   - KHÔNG upload Cloudinary.
   - Xóa ngay sau khi OCR xong.

3. Ghi log vào DB (extraction_logs).
"""
import threading
import os
from src.utils.logger import Log
from src.utils.cloudinary_utils import cloudinary_service


def _should_store_file(user_id: str | None, doc_id: str | None) -> tuple[bool, dict]:
    """
    Kiểm tra xem user/workspace có bật flag `allow_source_file_storage` không.
    Ưu tiên: workspace setting > user setting > default (False).

    Returns:
        (should_store: bool, context: dict) — context dùng khi lưu metadata.
    """
    context = {
        "account_id": None,
        "workspace_id": None,
        "retention_days": 7,
    }
    if not user_id:
        return False, context

    try:
        from src.repositories.users_repository import users_repo
        from src.repositories.documents_repository import documents_repo

        user = users_repo.find_by_id(user_id)
        if not user:
            return False, context

        context["account_id"] = str(user.get("account_id")) if user.get("account_id") else None

        # Lấy workspace_id từ document nếu có
        if doc_id:
            doc = documents_repo.find_by_id(doc_id)
            if doc:
                ws_id = doc.get("workspace_id")
                context["workspace_id"] = str(ws_id) if ws_id else None

                # Check workspace setting
                if ws_id:
                    from src.repositories.workspaces_repository import workspaces_repo
                    ws = workspaces_repo.find_by_id(str(ws_id))
                    if ws and ws.get("allow_source_file_storage", False):
                        context["retention_days"] = ws.get("file_retention_days", 7)
                        return True, context

        # Check user setting
        if user.get("allow_source_file_storage", False):
            context["retention_days"] = user.get("file_retention_days", 7)
            return True, context

    except Exception as e:
        Log.warning(f"[BG-TASK] Could not resolve storage flag: {e}")

    return False, context


def run_background_upload_and_log(
    user_id,
    doc_type,
    file_paths,
    info,
    metadata=None,
    document_id=None,
):
    """
    Spawns a background thread:
    1. Upload ảnh lên Cloudinary (private) nếu flag cho phép.
    2. Xóa toàn bộ file tạm.
    3. Ghi log vào DB.
    """
    def task():
        try:
            should_store, storage_ctx = _should_store_file(user_id, document_id)

            for f_path in (file_paths or []):
                if not f_path or f_path.startswith("http"):
                    continue
                if not os.path.exists(f_path):
                    continue

                original_name = os.path.basename(f_path)
                is_image = cloudinary_service.is_image_file(original_name)

                if is_image and should_store and cloudinary_service.configured:
                    # ── Upload private ─────────────────────────────────────────
                    Log.info(f"[BG-TASK] ☁️ Private upload: {original_name}")
                    result = cloudinary_service.upload_private(
                        f_path,
                        folder="ocr_source_images",
                    )
                    if result:
                        from src.repositories.file_storage_repository import file_storage_repo
                        file_storage_repo.save_file_metadata(
                            document_id=str(document_id) if document_id else "",
                            owner_user_id=str(user_id),
                            cloudinary_public_id=result["public_id"],
                            original_filename=original_name,
                            resource_type=result.get("resource_type", "image"),
                            account_id=storage_ctx.get("account_id"),
                            workspace_id=storage_ctx.get("workspace_id"),
                            retention_days=storage_ctx.get("retention_days", 7),
                        )
                else:
                    if not is_image:
                        Log.debug(f"[BG-TASK] 🚫 Non-image, skip Cloudinary: {original_name}")
                    elif not should_store:
                        Log.debug(f"[BG-TASK] 🚫 Storage flag off, skip: {original_name}")

            # ── Log to DB ─────────────────────────────────────────────────────
            from src.services.log_service import log_service
            log_service.save_logs(
                user_id, doc_type, file_paths, info,
                metadata=metadata, document_id=document_id
            )
            Log.info(f"[BG-TASK] 💾 DB log saved. doc_id={document_id}")

        except Exception as e:
            Log.error(f"[BG-TASK] ❌ Error in background task: {e}")

        finally:
            # ── Cleanup ALL temp files ─────────────────────────────────────────
            for f_path in (file_paths or []):
                if f_path and os.path.exists(f_path) and not f_path.startswith("http"):
                    try:
                        os.remove(f_path)
                        Log.debug(f"[BG-TASK] 🗑️ Cleaned: {f_path}")
                    except Exception as cleanup_e:
                        Log.warning(f"[BG-TASK] ⚠️ Cleanup failed for {f_path}: {cleanup_e}")

    thread = threading.Thread(target=task, daemon=True)
    thread.start()
    Log.info(f"[BG-TASK] 🚀 Background task started for user={user_id} doc={document_id}")
