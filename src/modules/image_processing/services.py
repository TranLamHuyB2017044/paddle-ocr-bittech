"""
Photo Service
Business logic xử lý ảnh thẻ theo batch.
Tách biệt hoàn toàn khỏi Flask route để dễ test và reuse.
"""
import gc
import io
import os
import time
import traceback
from datetime import datetime, timedelta

from PIL import Image, ImageColor, UnidentifiedImageError

from src.shared.utils.logger import Log
from src.core.config import (
    PHOTO_BATCH_TIMEOUT_SECONDS,
    PHOTO_SIGNED_URL_EXPIRY_SECONDS,
    PHOTO_TEMP_RETENTION_DAYS,
)
from src.shared.models.model_loader import model_loader
from src.shared.utils.cloudinary_utils import cloudinary_service
from src.modules.image_processing.image_utils import (
    PHOTO_SIZES,
    BG_COLORS,
    normalize_input,
    align_face,
    validate_image_size,
    detect_face,
    validate_photo_quality,
    detect_source_bg_color,
    remove_color_spill,
    refine_alpha_edge,
    crop_portrait_rgb,
    crop_portrait_rgba,
)

# ─── Config ───────────────────────────────────────────────────────────────────

# Giới hạn an toàn cho server nhỏ không GPU
MAX_FILES_PER_BATCH   = 10          # Tối đa 10 file/request
MAX_FILE_SIZE_BYTES   = 5 * 1024 * 1024   # 5 MB/file
MAX_BATCH_SIZE_BYTES  = 30 * 1024 * 1024  # 30 MB tổng cả batch
PHOTO_DOCUMENT_PREFIX = "photo:"


class PhotoStorageError(RuntimeError):
    """Raised khi không thể lưu hoặc cấp URL ảnh tạm trên Cloudinary."""
    pass


def _photo_document_id(session_id: str) -> str:
    return f"{PHOTO_DOCUMENT_PREFIX}{session_id}"


def ensure_photo_storage_ready() -> None:
    if not cloudinary_service.configured:
        raise PhotoStorageError(
            "Cloudinary chưa được cấu hình. Kiểm tra CLOUDINARY_CLOUD_NAME, "
            "CLOUDINARY_API_KEY và CLOUDINARY_API_SECRET."
        )


def _safe_path_component(value: str) -> str:
    return "".join(ch for ch in value if ch.isalnum() or ch in ("-", "_"))[:80] or "unknown"


def persist_photo_preview(
    img: Image.Image,
    *,
    session_id: str,
    owner_user_id: str,
    account_id: str | None,
    item_id: str,
    kind: str,
    original_filename: str,
) -> dict:
    """Upload ảnh preview private lên Cloudinary và lưu metadata retention 30 ngày."""
    from src.modules.ocr.repositories.file_storage_repository import file_storage_repo

    ensure_photo_storage_ready()
    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, format="JPEG", quality=95, dpi=(300, 300))
    buffer.seek(0)

    safe_owner = _safe_path_component(owner_user_id)
    safe_session = _safe_path_component(session_id)
    safe_item = _safe_path_component(item_id)
    safe_kind = _safe_path_component(kind)
    public_id = f"{safe_kind}_{safe_item}"
    folder = f"photo_temp/{safe_owner}/{safe_session}"

    upload = cloudinary_service.upload_private(
        buffer,
        public_id=public_id,
        folder=folder,
    )
    if not upload or not upload.get("public_id"):
        raise PhotoStorageError("Không thể upload ảnh tạm lên Cloudinary.")

    cloud_public_id = upload["public_id"]
    try:
        record_id = file_storage_repo.save_file_metadata(
            document_id=_photo_document_id(session_id),
            owner_user_id=str(owner_user_id),
            account_id=str(account_id) if account_id else None,
            cloudinary_public_id=cloud_public_id,
            original_filename=original_filename,
            resource_type=upload.get("resource_type", "image"),
            retention_days=PHOTO_TEMP_RETENTION_DAYS,
        )
    except Exception as e:
        cloudinary_service.delete_image(
            cloud_public_id,
            resource_type=upload.get("resource_type", "image"),
        )
        raise PhotoStorageError("Không thể lưu metadata ảnh tạm.") from e

    signed_url = cloudinary_service.generate_signed_url(
        cloud_public_id,
        resource_type=upload.get("resource_type", "image"),
        expires_in_seconds=PHOTO_SIGNED_URL_EXPIRY_SECONDS,
    )
    if not signed_url:
        cloudinary_service.delete_image(
            cloud_public_id,
            resource_type=upload.get("resource_type", "image"),
        )
        file_storage_repo.mark_deleted(record_id)
        raise PhotoStorageError("Không thể tạo signed URL cho ảnh tạm.")

    return {
        "url": signed_url,
        "record_id": record_id,
        "public_id": cloud_public_id,
        "url_expires_in_seconds": PHOTO_SIGNED_URL_EXPIRY_SECONDS,
        "retention_expires_at": (
            datetime.now() + timedelta(days=PHOTO_TEMP_RETENTION_DAYS)
        ).isoformat(),
    }


def _delete_persisted_asset(asset: dict) -> None:
    """Best-effort rollback nếu upload asset thứ hai của một item thất bại."""
    from src.modules.ocr.repositories.file_storage_repository import file_storage_repo

    public_id = asset.get("public_id")
    record_id = asset.get("record_id")
    if public_id and cloudinary_service.delete_image(public_id) and record_id:
        file_storage_repo.mark_deleted(record_id)


def _alignment_warnings(alignment: dict) -> list[str]:
    """Diễn đạt đúng face roll; không gọi nhầm là độ nghiêng của toàn ảnh."""
    angle = float(alignment.get("face_roll_degrees", 0.0))
    absolute_angle = abs(angle)
    if absolute_angle < float(alignment.get("warning_threshold_degrees", 5.0)):
        return []
    if alignment.get("applied"):
        return [
            f"Khuôn mặt nghiêng theo trục landmark ({angle:.1f}°). "
            "Hệ thống đã tự động căn thẳng."
        ]
    return [
        f"Khuôn mặt hơi nghiêng theo trục landmark ({angle:.1f}°), "
        "nhưng tổng thể ảnh được giữ nguyên. Client có thể gửi auto_align=true nếu muốn căn thẳng."
    ]


# ─── Validation ───────────────────────────────────────────────────────────────

class BatchValidationError(Exception):
    """Raised khi batch request vi phạm giới hạn — dừng toàn bộ request."""
    pass


def validate_batch_request(files, process_type: str, size_param: str, bg_color_param: str):
    """
    Validate toàn bộ batch trước khi xử lý.
    Raise BatchValidationError nếu vi phạm — trả 400 ngay, không tốn CPU.
    """
    if not files:
        raise BatchValidationError("Không có file nào được gửi lên.")

    if len(files) > MAX_FILES_PER_BATCH:
        raise BatchValidationError(
            f"Vượt quá giới hạn số file. Tối đa {MAX_FILES_PER_BATCH} file/request, "
            f"bạn gửi {len(files)} file."
        )

    if process_type not in ("crop", "full"):
        raise BatchValidationError(
            f"Tham số 'type' không hợp lệ: '{process_type}'. Chỉ chấp nhận 'crop' hoặc 'full'."
        )

    if size_param not in PHOTO_SIZES:
        raise BatchValidationError(
            f"Tham số 'size' không hợp lệ: '{size_param}'. "
            f"Chỉ chấp nhận: {list(PHOTO_SIZES.keys())}."
        )

    # Validate bg_color chỉ khi type=full
    if process_type == "full":
        bg_hex = BG_COLORS.get(bg_color_param, bg_color_param)
        try:
            ImageColor.getcolor(bg_hex, "RGBA")
        except (ValueError, AttributeError):
            raise BatchValidationError(
                f"Tham số 'bg_color' không hợp lệ: '{bg_color_param}'."
            )

    # Kiểm tra dung lượng từng file và tổng batch
    total_bytes = 0
    for f in files:
        f.stream.seek(0, 2)  # Seek to end
        size = f.stream.tell()
        f.stream.seek(0)     # Reset về đầu

        if size <= 0:
            raise BatchValidationError(f"File '{f.filename}' rỗng.")

        if size > MAX_FILE_SIZE_BYTES:
            raise BatchValidationError(
                f"File '{f.filename}' quá lớn ({size // 1024 // 1024}MB). "
                f"Tối đa {MAX_FILE_SIZE_BYTES // 1024 // 1024}MB/file."
            )
        total_bytes += size

    if total_bytes > MAX_BATCH_SIZE_BYTES:
        raise BatchValidationError(
            f"Tổng dung lượng batch ({total_bytes // 1024 // 1024}MB) "
            f"vượt quá giới hạn {MAX_BATCH_SIZE_BYTES // 1024 // 1024}MB."
        )


# ─── Single Item Processors ───────────────────────────────────────────────────

def _process_crop(
    file_stream,
    original_filename: str,
    item_id: str,
    target_w: int,
    target_h: int,
    ignore_warnings: bool,
    auto_align: bool,
    session_id: str,
    owner_user_id: str,
    account_id: str | None,
) -> dict:
    """
    Pipeline type=crop: Chỉ normalize + detect face + crop RGB.
    """
    img_rgb = None
    result: dict = _failed_item(item_id, original_filename, "Lỗi không xác định.")
    try:
        # 1. Normalize và Align
        img_rgb = normalize_input(file_stream)
        img_rgb, alignment = align_face(img_rgb, force_align=auto_align)
        
        # 2. Validate
        tilt_warning = _alignment_warnings(alignment)
        res_warnings = validate_image_size(img_rgb)
        all_res_warnings = res_warnings + tilt_warning

        face_bbox = detect_face(img_rgb)
        if face_bbox is None:
            result = _failed_item(item_id, original_filename, "Không tìm thấy khuôn mặt.")
        else:
            # 2.1 Validate chất lượng ảnh (chỉ lấy thông tin, không chặn xử lý)
            quality_warnings = validate_photo_quality(img_rgb, face_bbox)
            all_warnings = all_res_warnings + quality_warnings

            # 3. LUÔN LUÔN Cắt ảnh thẻ nếu tìm thấy mặt
            cropped = crop_portrait_rgb(img_rgb, face_bbox, target_w, target_h)
            if cropped is None:
                result = _failed_item(item_id, original_filename, "Không thể crop ảnh.")
            else:
                # 4. Upload ảnh gốc và ảnh crop ở chế độ authenticated.
                original_asset = persist_photo_preview(
                    img_rgb,
                    session_id=session_id,
                    owner_user_id=owner_user_id,
                    account_id=account_id,
                    item_id=item_id,
                    kind="original",
                    original_filename=f"original_{item_id}.jpg",
                )
                try:
                    cropped_asset = persist_photo_preview(
                        cropped,
                        session_id=session_id,
                        owner_user_id=owner_user_id,
                        account_id=account_id,
                        item_id=item_id,
                        kind=f"photo_{target_w}x{target_h}",
                        original_filename=f"photo_{target_w}x{target_h}_{item_id}.jpg",
                    )
                except Exception:
                    _delete_persisted_asset(original_asset)
                    raise

                result = {
                    "id": item_id,
                    "original_filename": original_filename,
                    "status": "success",
                    "warnings": all_warnings,
                    "warnings_ignored": bool(ignore_warnings and all_warnings),
                    "alignment": alignment,
                    "output_width": target_w,
                    "output_height": target_h,
                    "background_color": None,
                    "original_url": original_asset["url"],
                    "cropped_url": cropped_asset["url"],
                    "url_expires_in_seconds": PHOTO_SIGNED_URL_EXPIRY_SECONDS,
                    "retention_expires_at": cropped_asset["retention_expires_at"],
                }

    except PhotoStorageError:
        raise
    except UnidentifiedImageError:
        result = _failed_item(item_id, original_filename, "File không phải ảnh hợp lệ hoặc bị hỏng.")
    except Exception as e:
        Log.error(f"[CROP] Error [{item_id}] {original_filename}: {e}")
        Log.error(traceback.format_exc())
        result = _failed_item(item_id, original_filename, f"Lỗi xử lý: {str(e)}")

    del img_rgb
    gc.collect()
    return result


def _process_full(
    file_stream,
    original_filename: str,
    item_id: str,
    target_w: int,
    target_h: int,
    bg_rgba: tuple[int, int, int, int],
    ignore_warnings: bool,
    auto_align: bool,
    session_id: str,
    owner_user_id: str,
    account_id: str | None,
) -> dict:
    """Normalize → align → detect → MODNet remove bg → crop → composite → Cloudinary."""
    img_rgb = None
    started = time.perf_counter()
    try:
        img_rgb = normalize_input(file_stream)
        img_rgb, alignment = align_face(img_rgb, force_align=auto_align)
        face_bbox = detect_face(img_rgb)
        if face_bbox is None:
            return _failed_item(item_id, original_filename, "Không tìm thấy khuôn mặt.")

        warnings_list = validate_image_size(img_rgb)
        warnings_list.extend(_alignment_warnings(alignment))
        warnings_list.extend(validate_photo_quality(img_rgb, face_bbox))

        source_bg = detect_source_bg_color(img_rgb, face_bbox)
        if source_bg == "white":
            # Client chủ động hiển thị cảnh báo; không chặn trường hợp áo trắng/nền trắng.
            warnings_list.append(
                "Ảnh có nền trắng. Nếu trang phục cũng màu trắng, viền tách nền có thể chưa chính xác."
            )

        from rembg import remove
        session = model_loader.rembg_session
        if session is None:
            raise RuntimeError("Không thể khởi tạo model MODNet.")

        no_bg = remove(img_rgb.convert("RGBA"), session=session)
        if not isinstance(no_bg, Image.Image):
            no_bg = Image.open(io.BytesIO(no_bg)).convert("RGBA")
        else:
            no_bg = no_bg.convert("RGBA")

        no_bg = remove_color_spill(no_bg, source_bg)
        no_bg = refine_alpha_edge(no_bg, source_bg)
        cropped_rgba = crop_portrait_rgba(no_bg, target_w, target_h, face_bbox)
        if cropped_rgba is None:
            return _failed_item(item_id, original_filename, "Không thể crop ảnh sau khi tách nền.")

        final_image = Image.new("RGBA", (target_w, target_h), bg_rgba)
        final_image.alpha_composite(cropped_rgba, (0, 0))
        final_rgb = final_image.convert("RGB")

        original_asset = persist_photo_preview(
            img_rgb,
            session_id=session_id,
            owner_user_id=owner_user_id,
            account_id=account_id,
            item_id=item_id,
            kind="original",
            original_filename=f"original_{item_id}.jpg",
        )
        try:
            final_asset = persist_photo_preview(
                final_rgb,
                session_id=session_id,
                owner_user_id=owner_user_id,
                account_id=account_id,
                item_id=item_id,
                kind=f"full_{target_w}x{target_h}",
                original_filename=f"photo_{target_w}x{target_h}_{item_id}.jpg",
            )
        except Exception:
            _delete_persisted_asset(original_asset)
            raise
        Log.info(
            f"[PHOTO ITEM] session={session_id} item={item_id} type=full "
            f"source_bg={source_bg} duration_ms={int((time.perf_counter() - started) * 1000)}"
        )
        return {
            "id": item_id,
            "original_filename": original_filename,
            "status": "success",
            "warnings": warnings_list,
            "warnings_ignored": bool(ignore_warnings and warnings_list),
            "alignment": alignment,
            "output_width": target_w,
            "output_height": target_h,
            "background_color": f"#{bg_rgba[0]:02x}{bg_rgba[1]:02x}{bg_rgba[2]:02x}",
            "original_url": original_asset["url"],
            "cropped_url": final_asset["url"],
            "url_expires_in_seconds": PHOTO_SIGNED_URL_EXPIRY_SECONDS,
            "retention_expires_at": final_asset["retention_expires_at"],
        }
    except PhotoStorageError:
        raise
    except UnidentifiedImageError:
        return _failed_item(item_id, original_filename, "File không phải ảnh hợp lệ hoặc bị hỏng.")
    except Exception as e:
        Log.error(f"[FULL] Error [{item_id}] {original_filename}: {e}")
        Log.error(traceback.format_exc())
        return _failed_item(item_id, original_filename, f"Lỗi xử lý: {str(e)}")
    finally:
        del img_rgb
        gc.collect()


def _failed_item(item_id: str, filename: str, error: str, original_url: str | None = None) -> dict:
    """Helper tạo object lỗi chuẩn."""
    return {
        "id": item_id,
        "original_filename": filename,
        "status": "failed",
        "error": error,
        "original_url": original_url,
        "cropped_url": None,
    }


# ─── Batch Processor ──────────────────────────────────────────────────────────

def process_batch(
    files,
    process_type: str,
    size_param: str,
    bg_color_param: str,
    ignore_warnings: bool,
    session_id: str,
    owner_user_id: str,
    account_id: str | None = None,
    auto_align: bool = False,
) -> list[dict]:
    """
    Xử lý batch nhiều file ảnh tuần tự.
    """
    target_w, target_h = PHOTO_SIZES[size_param]
    ensure_photo_storage_ready()
    results = []
    batch_started = time.perf_counter()
    bg_hex = BG_COLORS.get(bg_color_param, bg_color_param)
    bg_rgba = ImageColor.getcolor(bg_hex, "RGBA")

    for f in files:
        item_id = os.urandom(4).hex()
        filename = f.filename or "unknown.jpg"

        if time.perf_counter() - batch_started >= PHOTO_BATCH_TIMEOUT_SECONDS:
            Log.warning(
                f"[PHOTO BATCH] Time budget exceeded: session={session_id} "
                f"limit_seconds={PHOTO_BATCH_TIMEOUT_SECONDS}"
            )
            results.append(
                _failed_item(
                    item_id,
                    filename,
                    f"Batch vượt giới hạn xử lý {PHOTO_BATCH_TIMEOUT_SECONDS} giây.",
                )
            )
            continue

        item_started = time.perf_counter()
        if process_type == "full":
            result = _process_full(
                f.stream, filename, item_id, target_w, target_h, bg_rgba,
                ignore_warnings, auto_align, session_id, owner_user_id, account_id,
            )
        else:
            result = _process_crop(
                f.stream, filename, item_id, target_w, target_h,
                ignore_warnings, auto_align, session_id, owner_user_id, account_id,
            )
        results.append(result)
        alignment_log = result.get("alignment") or {}
        Log.info(
            f"[PHOTO ITEM] session={session_id} item={item_id} type={process_type} "
            f"size={size_param} status={result['status']} "
            f"face_roll={alignment_log.get('face_roll_degrees')} "
            f"alignment_applied={alignment_log.get('applied')} "
            f"alignment_detector={alignment_log.get('detector')} "
            f"duration_ms={int((time.perf_counter() - item_started) * 1000)}"
        )

    Log.info(
        f"[BATCH] Done: {sum(1 for r in results if r['status'] == 'success')} success, "
        f"{sum(1 for r in results if r['status'] == 'failed')} failed / {len(results)} total. "
        f"session={session_id} type={process_type} size={size_param} "
        f"duration_ms={int((time.perf_counter() - batch_started) * 1000)}"
    )
    return results


def clear_session_data(session_id: str, owner_user_id: str) -> dict:
    """
    Xóa asset Cloudinary của session thuộc đúng owner và soft-delete metadata.
    """
    if not session_id or len(session_id) < 3 or session_id == "all":
        return {"success": False, "deleted": 0, "failed": 0}

    from src.modules.ocr.repositories.file_storage_repository import file_storage_repo

    records = file_storage_repo.find_by_document_and_owner(
        _photo_document_id(session_id),
        str(owner_user_id),
    )
    deleted_ids = []
    failed = 0
    try:
        for record in records:
            if cloudinary_service.delete_image(
                record.get("cloudinary_public_id"),
                resource_type=record.get("resource_type", "image"),
            ):
                deleted_ids.append(str(record["_id"]))
            else:
                failed += 1
        file_storage_repo.mark_deleted_many(deleted_ids)
        Log.info(
            f"[PHOTO CLEAR] owner={owner_user_id} session={session_id} "
            f"deleted={len(deleted_ids)} failed={failed}"
        )
        return {
            "success": failed == 0,
            "deleted": len(deleted_ids),
            "failed": failed,
        }
    except Exception as e:
        Log.error(f"[PHOTO CLEAR] owner={owner_user_id} session={session_id} error={e}")
        return {"success": False, "deleted": len(deleted_ids), "failed": failed + 1}
