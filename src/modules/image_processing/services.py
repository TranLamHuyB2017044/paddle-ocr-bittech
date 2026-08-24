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

import requests
from PIL import Image, ImageColor, ImageOps, UnidentifiedImageError

from src.shared.utils.logger import Log
from src.core.config import (
    PHOTO_BATCH_TIMEOUT_SECONDS,
    PHOTO_SIGNED_URL_EXPIRY_SECONDS,
    PHOTO_TEMP_RETENTION_DAYS,
    FILES_API_URL,
    FILES_API_UPLOAD_ENDPOINT,
    FILES_API_SYSTEM_ID,
    FILES_API_USER_ID,
    FILES_API_ALIAS,
    FILES_API_KEY,
)
from src.shared.models.model_loader import model_loader
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
    calculate_face_crop_box,
)

# ─── Config ───────────────────────────────────────────────────────────────────

# Giới hạn an toàn cho server nhỏ không GPU
MAX_FILES_PER_BATCH   = 10          # Tối đa 10 file/request
MAX_FILE_SIZE_BYTES   = 5 * 1024 * 1024   # 5 MB/file
MAX_BATCH_SIZE_BYTES  = 30 * 1024 * 1024  # 30 MB tổng cả batch
PHOTO_DOCUMENT_PREFIX = "photo:"


class PhotoStorageError(RuntimeError):
    """Raised khi không thể lưu hoặc cấp URL ảnh trên hệ thống file."""
    pass


def _photo_document_id(session_id: str) -> str:
    return f"{PHOTO_DOCUMENT_PREFIX}{session_id}"


def ensure_photo_storage_ready() -> None:
    if not (FILES_API_URL and FILES_API_KEY):
        raise PhotoStorageError(
            "Hệ thống file chưa được cấu hình. Kiểm tra FILES_API_URL và FILES_API_KEY."
        )


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
    """Upload ảnh preview lên hệ thống files.bittechx.cloud."""
    ensure_photo_storage_ready()
    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, format="JPEG", quality=95, dpi=(300, 300))
    buffer.seek(0)

    upload_filename = original_filename if original_filename.lower().endswith(('.jpg', '.jpeg', '.png')) else f"{original_filename}.jpg"
    upload_url = f"{FILES_API_URL.rstrip('/')}{FILES_API_UPLOAD_ENDPOINT}"

    files = {
        'files': (upload_filename, buffer, 'image/jpeg')
    }
    data = {
        'system_id': FILES_API_SYSTEM_ID,
        'user_id': str(owner_user_id) if owner_user_id else FILES_API_USER_ID,
        'alias': FILES_API_ALIAS,
        'file_system': False
    }
    headers = {
        'x-api-key': FILES_API_KEY
    }

    try:
        response = requests.post(upload_url, files=files, data=data, headers=headers, timeout=30)
        response.raise_for_status()
        upload_result = response.json()
    except Exception as e:
        Log.error(f"[PHOTO STORAGE] Error uploading to FILES_API: {e}")
        raise PhotoStorageError(f"Không thể upload ảnh lên hệ thống file: {str(e)}")

    base_url = (FILES_API_URL or "https://files.bittechx.cloud").rstrip('/')
    final_url = None
    if upload_result and isinstance(upload_result, dict):
        data_obj = upload_result.get('data') if isinstance(upload_result.get('data'), dict) else upload_result
        results = data_obj.get('results', [])
        if isinstance(results, list) and len(results) > 0:
            first_result = results[0]
            if isinstance(first_result, dict):
                file_info = first_result.get('file', {})
                if isinstance(file_info, dict):
                    public_path = file_info.get('publicPath') or file_info.get('path')
                    if public_path:
                        final_url = f"{base_url}/{public_path.lstrip('/')}"
        if not final_url:
            if 'file_url' in data_obj:
                final_url = data_obj['file_url']
            elif 'url' in data_obj:
                final_url = data_obj['url']
            elif 'publicPath' in data_obj:
                final_url = f"{base_url}/{data_obj['publicPath'].lstrip('/')}"

    if not final_url:
        raise PhotoStorageError("Không nhận được URL hợp lệ từ hệ thống file.")

    return {
        "url": final_url,
        "public_id": item_id,
        "url_expires_in_seconds": PHOTO_SIGNED_URL_EXPIRY_SECONDS,
        "retention_expires_at": (
            datetime.now() + timedelta(days=PHOTO_TEMP_RETENTION_DAYS)
        ).isoformat(),
    }


def _delete_persisted_asset(asset: dict) -> None:
    """Best-effort rollback nếu upload asset thứ hai của một item thất bại."""
    pass


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


def validate_batch_request(files, process_type: str, size_param: str | None, bg_color_param: str | None):
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

    if process_type not in ("crop", "change_bg", "full"):
        raise BatchValidationError(
            f"Tham số 'type' không hợp lệ: '{process_type}'. Chỉ chấp nhận 'crop', 'change_bg' hoặc 'full'."
        )

    if process_type in ("crop", "full"):
        if not size_param or size_param not in PHOTO_SIZES:
            raise BatchValidationError(
                f"Tham số 'size' không hợp lệ: '{size_param}'. "
                f"Chỉ chấp nhận: {list(PHOTO_SIZES.keys())}."
            )

    # Validate bg_color chỉ khi type=full hoặc type=change_bg
    if process_type in ("full", "change_bg"):
        if not bg_color_param:
            raise BatchValidationError("Tham số 'bg_color' (hoặc 'bg') là bắt buộc khi đổi nền.")
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
            cropped, crop_box = crop_portrait_rgb(img_rgb, face_bbox, target_w, target_h)
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
                    "crop_box": crop_box,
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
        cropped_rgba, crop_box = crop_portrait_rgba(no_bg, target_w, target_h, face_bbox)
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
            "crop_box": crop_box,
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


def _process_change_bg(
    file_stream,
    original_filename: str,
    item_id: str,
    bg_rgba: tuple[int, int, int, int],
    ignore_warnings: bool,
    auto_align: bool,
    session_id: str,
    owner_user_id: str,
    account_id: str | None,
) -> dict:
    """Normalize → align → detect → MODNet remove bg → composite on original size → Cloudinary."""
    img_rgb = None
    started = time.perf_counter()
    try:
        img_rgb = normalize_input(file_stream)
        img_rgb, alignment = align_face(img_rgb, force_align=auto_align)
        face_bbox = detect_face(img_rgb)

        warnings_list = validate_image_size(img_rgb)
        warnings_list.extend(_alignment_warnings(alignment))
        crop_box = None
        if face_bbox is not None:
            warnings_list.extend(validate_photo_quality(img_rgb, face_bbox))
            source_bg = detect_source_bg_color(img_rgb, face_bbox)
            fx, fy, fw, fh = calculate_face_crop_box(img_rgb.size, face_bbox, aspect_ratio="3:4")
            crop_box = {
                "x": int(fx),
                "y": int(fy),
                "width": int(fw),
                "height": int(fh),
            }
        else:
            source_bg = "none"

        if source_bg == "white":
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

        # Composite trên kích thước ảnh gốc (không crop portrait kích thước thẻ)
        orig_w, orig_h = img_rgb.size
        final_image = Image.new("RGBA", (orig_w, orig_h), bg_rgba)
        final_image.alpha_composite(no_bg, (0, 0))
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
                kind=f"change_bg_{orig_w}x{orig_h}",
                original_filename=f"photo_{orig_w}x{orig_h}_{item_id}.jpg",
            )
        except Exception:
            _delete_persisted_asset(original_asset)
            raise

        Log.info(
            f"[PHOTO ITEM] session={session_id} item={item_id} type=change_bg "
            f"source_bg={source_bg} duration_ms={int((time.perf_counter() - started) * 1000)}"
        )
        return {
            "id": item_id,
            "original_filename": original_filename,
            "status": "success",
            "crop_box": crop_box,
            "warnings": warnings_list,
            "warnings_ignored": bool(ignore_warnings and warnings_list),
            "alignment": alignment,
            "output_width": orig_w,
            "output_height": orig_h,
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
        Log.error(f"[CHANGE_BG] Error [{item_id}] {original_filename}: {e}")
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
        "crop_box": None,
        "error": error,
        "original_url": original_url,
        "cropped_url": None,
    }


# ─── Batch Processor ──────────────────────────────────────────────────────────

def process_batch(
    files,
    process_type: str,
    size_param: str | None,
    bg_color_param: str | None,
    ignore_warnings: bool,
    session_id: str,
    owner_user_id: str,
    account_id: str | None = None,
    auto_align: bool = False,
) -> list[dict]:
    """
    Xử lý batch nhiều file ảnh tuần tự.
    """
    target_w, target_h = (PHOTO_SIZES[size_param] if size_param and size_param in PHOTO_SIZES else (None, None))
    ensure_photo_storage_ready()
    results = []
    batch_started = time.perf_counter()
    bg_rgba = None
    if bg_color_param:
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
        elif process_type == "change_bg":
            result = _process_change_bg(
                f.stream, filename, item_id, bg_rgba,
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
    Xóa asset / session data.
    """
    if not session_id or len(session_id) < 3 or session_id == "all":
        return {"success": False, "deleted": 0, "failed": 0}

    Log.info(f"[PHOTO CLEAR] session={session_id} owner={owner_user_id}")
    return {
        "success": True,
        "deleted": 1,
        "failed": 0,
    }
