"""
CloudinaryService — Nâng cấp hỗ trợ:
  - upload_private(): upload ở chế độ authenticated (không public).
  - generate_signed_url(): tạo URL ngắn hạn (signed delivery URL).
  - delete_image(): xóa file khỏi Cloudinary (dùng cho retention job).
  - upload_image(): giữ nguyên tương thích ngược (public upload — chỉ dùng cho avatar).
"""
import cloudinary
import cloudinary.uploader
import cloudinary.utils
from src.core.config import CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET
from src.shared.utils.logger import Log

# Thời gian mặc định signed URL (giây). 15 phút.
DEFAULT_SIGNED_URL_EXPIRY_SEC = 15 * 60

IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}


class CloudinaryService:
    _instance: "CloudinaryService | None" = None
    configured: bool = False  # Khai báo class-level để type checker nhận ra

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CloudinaryService, cls).__new__(cls)
            if CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET:
                cloudinary.config(
                    cloud_name=CLOUDINARY_CLOUD_NAME,
                    api_key=CLOUDINARY_API_KEY,
                    api_secret=CLOUDINARY_API_SECRET,
                    secure=True,
                )
                cls._instance.configured = True
                Log.info("[CLOUDINARY] ✅ Configured")
            else:
                cls._instance.configured = False
                Log.warning("[CLOUDINARY] ⚠️ Not Configured (Missing ENV vars)")
        return cls._instance

    # ── Public upload (backward compat — dùng cho avatar) ─────────────────────
    def upload_image(self, file_path: str) -> str | None:
        """
        Upload một file lên Cloudinary ở chế độ public.
        CHỈ dùng cho avatar / ảnh đại diện — KHÔNG dùng cho ảnh OCR nhạy cảm.

        Returns:
            secure_url hoặc None nếu lỗi.
        """
        if not self.configured:
            return None
        try:
            response = cloudinary.uploader.upload(
                file_path,
                folder="user_avatars",
                use_filename=True,
                unique_filename=True,
                resource_type="image",
            )
            return response.get("secure_url")
        except Exception as e:
            Log.error(f"[CLOUDINARY] ❌ Public upload failed: {e}")
            return None

    # ── Private upload (cho ảnh gốc OCR) ──────────────────────────────────────
    def upload_private(
        self,
        file_path,
        public_id: str | None = None,
        folder: str = "ocr_source_images",
    ) -> dict | None:
        """
        Upload file ảnh OCR lên Cloudinary ở chế độ AUTHENTICATED (private).
        Ảnh sẽ không thể truy cập qua URL thông thường — chỉ qua signed URL.

        Args:
            file_path: Đường dẫn file hoặc file-like object/BytesIO.
            public_id: ID tùy chỉnh (không bắt buộc).
            folder:    Folder trên Cloudinary.

        Returns:
            dict chứa {public_id, resource_type, secure_url} hoặc None nếu lỗi.
        """
        if not self.configured:
            Log.warning("[CLOUDINARY] Skipping private upload — not configured.")
            return None
        try:
            upload_params = {
                "folder": folder,
                "resource_type": "image",
                "type": "authenticated",   # Key: private / authenticated delivery
                "use_filename": isinstance(file_path, (str, bytes)),
                "unique_filename": public_id is None,
            }
            if public_id:
                upload_params["public_id"] = public_id

            response = cloudinary.uploader.upload(file_path, **upload_params)

            Log.info(
                f"[CLOUDINARY] 🔒 Private upload OK: {response.get('public_id')} "
                f"(type={response.get('type')})"
            )
            return {
                "public_id": response.get("public_id"),
                "resource_type": response.get("resource_type", "image"),
                "type": response.get("type", "authenticated"),
                "bytes": response.get("bytes"),
                "format": response.get("format"),
            }
        except Exception as e:
            Log.error(f"[CLOUDINARY] ❌ Private upload failed: {e}")
            return None

    # ── Generate signed (short-lived) URL ─────────────────────────────────────
    def generate_signed_url(
        self,
        public_id: str,
        resource_type: str = "image",
        expires_in_seconds: int = DEFAULT_SIGNED_URL_EXPIRY_SEC,
    ) -> str | None:
        """
        Tạo signed delivery URL ngắn hạn cho file private.

        Args:
            public_id:         Cloudinary public_id của file.
            resource_type:     "image" | "raw".
            expires_in_seconds: Thời gian URL còn hợp lệ (giây). Mặc định 15 phút.

        Returns:
            Signed URL string hoặc None nếu lỗi.
        """
        if not self.configured:
            return None
        try:
            import time
            timestamp = int(time.time()) + expires_in_seconds

            url, _ = cloudinary.utils.cloudinary_url(
                public_id,
                resource_type=resource_type,
                type="authenticated",
                sign_url=True,
                secure=True,
                expires_at=timestamp,
            )
            Log.info(
                f"[CLOUDINARY] 🔗 Signed URL issued for {public_id!r} "
                f"(expires in {expires_in_seconds}s)"
            )
            return url
        except Exception as e:
            Log.error(f"[CLOUDINARY] ❌ Signed URL generation failed: {e}")
            return None

    # ── Delete ────────────────────────────────────────────────────────────────
    def delete_image(self, public_id: str, resource_type: str = "image") -> bool:
        """
        Xóa file khỏi Cloudinary. Dùng cho retention job.

        Returns:
            True nếu xóa thành công, False nếu lỗi.
        """
        if not self.configured:
            return False
        try:
            result = cloudinary.uploader.destroy(
                public_id,
                resource_type=resource_type,
                type="authenticated",
                invalidate=True,
            )
            # "not found" được xem là idempotent success: asset đã không còn tồn tại.
            ok = result.get("result") in ("ok", "not found")
            if ok:
                Log.info(f"[CLOUDINARY] 🗑️ Deleted: {public_id}")
            else:
                Log.warning(f"[CLOUDINARY] ⚠️ Delete returned non-ok: {result}")
            return ok
        except Exception as e:
            Log.error(f"[CLOUDINARY] ❌ Delete failed for {public_id}: {e}")
            return False

    @staticmethod
    def is_image_file(filename: str) -> bool:
        """Kiểm tra xem file có phải ảnh không (dựa vào extension)."""
        if not filename or "." not in filename:
            return False
        ext = filename.rsplit(".", 1)[1].lower()
        return ext in IMAGE_EXTENSIONS


cloudinary_service = CloudinaryService()
