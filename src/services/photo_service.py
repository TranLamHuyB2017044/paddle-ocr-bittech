"""
Photo Service
Business logic xử lý ảnh thẻ theo batch.
Tách biệt hoàn toàn khỏi Flask route để dễ test và reuse.
"""
import gc
import os
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout

from PIL import Image, ImageColor, UnidentifiedImageError

from src.utils.logger import Log
from src.config import UPLOAD_FOLDER
from src.utils.image_processing import (
    PHOTO_SIZES, BG_COLORS,
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
    build_file_object,
)

# ─── Config ───────────────────────────────────────────────────────────────────

# Thư mục lưu ảnh preview tạm thời
PREVIEW_SUBFOLDER = "temp_previews"
PREVIEW_DIR = os.path.join(UPLOAD_FOLDER, PREVIEW_SUBFOLDER)

# Đảm bảo thư mục tồn tại
if not os.path.exists(PREVIEW_DIR):
    os.makedirs(PREVIEW_DIR, exist_ok=True)

# Giới hạn an toàn cho server nhỏ không GPU
MAX_FILES_PER_BATCH   = 10          # Tối đa 10 file/request
MAX_FILE_SIZE_BYTES   = 5 * 1024 * 1024   # 5 MB/file
MAX_BATCH_SIZE_BYTES  = 30 * 1024 * 1024  # 30 MB tổng cả batch
THREAD_WORKERS        = 3           # 3 threads song song (tối ưu cho 2-core CPU)
PER_ITEM_TIMEOUT_SEC  = 20          # Timeout mỗi ảnh 20s


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
) -> dict:
    """
    Pipeline type=crop: Chỉ normalize + detect face + crop RGB.
    """
    img_rgb = None
    result: dict = _failed_item(item_id, original_filename, "Lỗi không xác định.")
    try:
        # 1. Normalize và Align
        img_rgb = normalize_input(file_stream)
        img_rgb, tilt_angle = align_face(img_rgb)
        
        # Lưu ảnh gốc (đã xoay thẳng) để trả về URL
        original_filename_out = f"original_{item_id}.jpg"
        original_save_path = os.path.join(PREVIEW_DIR, original_filename_out)
        img_rgb.save(original_save_path, format="JPEG", quality=90)
        original_url = f"/uploads/{PREVIEW_SUBFOLDER}/{original_filename_out}"

        # 2. Validate
        tilt_warning = []
        if abs(tilt_angle) > 5.0:
            tilt_warning.append(f"Ảnh gốc bị nghiêng ({round(tilt_angle, 1)}°). Hệ thống đã tự động xoay thẳng.")
        res_warnings = validate_image_size(img_rgb)
        all_res_warnings = res_warnings + tilt_warning

        face_bbox = detect_face(img_rgb)
        if face_bbox is None:
            result = _failed_item(item_id, original_filename, "Không tìm thấy khuôn mặt.", original_url)
        else:
            # 2.1 Validate chất lượng ảnh (chỉ lấy thông tin, không chặn xử lý)
            quality_warnings = validate_photo_quality(img_rgb, face_bbox)
            all_warnings = all_res_warnings + quality_warnings

            # 3. LUÔN LUÔN Cắt ảnh thẻ nếu tìm thấy mặt
            cropped = crop_portrait_rgb(img_rgb, face_bbox, target_w, target_h)
            if cropped is None:
                result = _failed_item(item_id, original_filename, "Không thể crop ảnh.", original_url)
            else:
                # 4. Lưu ảnh đã cắt và tạo URL
                cropped_filename_out = f"photo_{target_w}x{target_h}_{item_id}.jpg"
                cropped_save_path = os.path.join(PREVIEW_DIR, cropped_filename_out)
                cropped.save(cropped_save_path, format="JPEG", quality=95, dpi=(300, 300))
                cropped_url = f"/uploads/{PREVIEW_SUBFOLDER}/{cropped_filename_out}"
                
                result = {
                    "id": item_id,
                    "original_filename": original_filename,
                    "status": "success",
                    "warnings": all_warnings, # Trả về cảnh báo để người dùng biết
                    "original_url": original_url,
                    "cropped_url": cropped_url,
                }

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
) -> dict:
    # Tạm thời vô hiệu hóa, sẽ triển khai sau
    return _failed_item(item_id, original_filename, "Tính năng 'full' đang được phát triển.")


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
) -> list[dict]:
    """
    Xử lý batch nhiều file ảnh tuần tự.
    """
    target_w, target_h = PHOTO_SIZES[size_param]
    results = []

    for f in files:
        item_id = os.urandom(4).hex()
        filename = f.filename or "unknown.jpg"
        
        # Xử lý tuần tự từng file
        result = _process_crop(f.stream, filename, item_id, target_w, target_h, ignore_warnings)
        results.append(result)

    Log.info(
        f"[BATCH] Done: {sum(1 for r in results if r['status'] == 'success')} success, "
        f"{sum(1 for r in results if r['status'] == 'failed')} failed / {len(results)} total."
    )
    return results
