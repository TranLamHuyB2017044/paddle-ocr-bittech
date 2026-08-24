"""
Photo Routes — API Endpoint xử lý ảnh thẻ.
Route handler thuần túy: validate request → gọi service → trả response.
"""
import uuid
from flask import Blueprint, request, jsonify, g

from src.shared.utils.auth_middleware import require_auth
from src.shared.utils.logger import Log
from src.shared.utils.rate_limit import get_limiter
from src.modules.image_processing.services import (
    validate_batch_request,
    process_batch,
    clear_session_data,
    persist_photo_preview,
    BatchValidationError,
    PhotoStorageError,
)
from src.modules.image_processing.image_utils import (
    calculate_face_crop_box,
    detect_face,
    get_face_landmarks,
    normalize_input,
)

photo_bp = Blueprint('photo_routes', __name__)

limiter = get_limiter()


@photo_bp.route("/api/photo/process", methods=["POST"])
@require_auth
@limiter.limit("20 per minute")
def process_photo():
    try:
        session_id = str(uuid.uuid4())

        # ── 1. Lấy danh sách file ─────────────────────────────────────────────
        files = request.files.getlist('files')

        # Hỗ trợ backward-compatible: nếu client gửi 'file' (single) thay vì 'files'
        if not files:
            single = request.files.get('file')
            if single:
                files = [single]

        # ── 2. Lấy & nhận diện thông minh params ──────────────────────────────
        raw_size = request.form.get('size')
        raw_bg   = request.form.get('bg_color') or request.form.get('bg')

        size_param     = raw_size.strip() if raw_size and raw_size.strip() else None
        bg_color_param = raw_bg.lower().strip() if raw_bg and raw_bg.strip() else None

        # Tự động suy luận process_type thông minh:
        # - Truyền size, không truyền bg -> crop
        # - Truyền bg, không truyền size -> change_bg
        # - Truyền cả 2 -> full
        # - Không truyền cả 2 -> mặc định crop 3x4
        if size_param and not bg_color_param:
            process_type = 'crop'
        elif bg_color_param and not size_param:
            process_type = 'change_bg'
        elif size_param and bg_color_param:
            process_type = 'full'
        else:
            process_type = 'crop'
            size_param   = '3x4'

        ignore_warnings = request.form.get('ignore_warnings', 'false').lower() == 'true'
        auto_align_raw  = request.form.get('auto_align', 'false').lower().strip()
        if auto_align_raw not in ("true", "false"):
            return jsonify({
                "statusCode": 400,
                "message": "Tham số 'auto_align' chỉ chấp nhận 'true' hoặc 'false'.",
            }), 400
        auto_align = auto_align_raw == "true"

        Log.info(
            f"[PHOTO API] Request: user={g.user_id}, session={session_id}, "
            f"type={process_type}, size={size_param}, "
            f"bg_color={bg_color_param}, files={len(files)}, "
            f"ignore_warnings={ignore_warnings}, auto_align={auto_align}"
        )

        # ── 3. Validate batch (fail fast, không tốn CPU) ──────────────────────
        try:
            validate_batch_request(files, process_type, size_param, bg_color_param)
        except BatchValidationError as e:
            Log.warning(
                f"[PHOTO API] Validation failed: user={g.user_id} "
                f"session={session_id} reason={e}"
            )
            return jsonify({"statusCode": 400, "message": str(e)}), 400

        # ── 4. Xử lý batch ────────────────────────────────────────────────────
        results = process_batch(
            files         = files,
            process_type  = process_type,
            size_param    = size_param,
            bg_color_param= bg_color_param,
            ignore_warnings = ignore_warnings,
            session_id    = session_id,
            owner_user_id = g.user_id,
            account_id    = g.user.get("account_id") if hasattr(g, "user") and isinstance(g.user, dict) else None,
            auto_align    = auto_align,
        )

        # ── 5. Build summary & Full URLs ──────────────────────────────────────
        total   = len(results)
        success = sum(1 for r in results if r["status"] == "success")
        failed  = total - success

        Log.info(
            f"[PHOTO API] Response ready. user={g.user_id} session={session_id} "
            f"success={success} failed={failed}"
        )

        return jsonify({
            "statusCode": 200,
            "session_id": session_id,
            "type":       process_type,
            "size":       size_param,
            "bg_color":   bg_color_param if process_type in ("full", "change_bg") else None,
            "auto_align": auto_align,
            "total":      total,
            "success":    success,
            "failed":     failed,
            "results":    results,
        }), 200

    except PhotoStorageError as e:
        Log.error(f"[PHOTO API] Storage unavailable: {e}")
        return jsonify({"statusCode": 503, "message": str(e)}), 503
    except Exception as e:
        Log.error(f"[PHOTO API] Unhandled error: {e}")
        import traceback
        Log.error(traceback.format_exc())
        return jsonify({"statusCode": 500, "message": "Lỗi hệ thống. Vui lòng thử lại."}), 500


@photo_bp.route("/api/photo/clear", methods=["POST"])
@require_auth
def clear_photo_session():
    """
    API endpoint để xóa các ảnh tạm thời của một session.
    """
    try:
        # Hỗ trợ lấy data từ cả JSON (application/json) hoặc Form Data (multipart/form-data, application/x-www-form-urlencoded)
        if request.is_json:
            data = request.json
            session_id = data.get('session_id') if data else None
        else:
            session_id = request.form.get('session_id')

        if not session_id:
            return jsonify({"statusCode": 400, "message": "session_id is required"}), 400

        if session_id == "all":
            return jsonify({
                "statusCode": 400,
                "message": "Không hỗ trợ xóa toàn bộ session.",
            }), 400

        clear_result = clear_session_data(session_id, g.user_id)
        
        if clear_result["success"]:
            return jsonify({
                "statusCode": 200,
                "message": f"Successfully cleared data for session {session_id}",
                **clear_result,
            }), 200
        else:
            return jsonify({
                "statusCode": 500,
                "message": f"Failed to clear all data for session {session_id}",
                **clear_result,
            }), 500

    except Exception as e:
        Log.error(f"[PHOTO API] Clear error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@photo_bp.route("/api/driver-center/ai/auto-crop", methods=["POST"])
@require_auth
@limiter.limit("20 per minute")
def auto_crop_face():
    try:
        file = request.files.get('image')
        if not file:
            file = request.files.get('file')
            if not file:
                files = request.files.getlist('files')
                if files:
                    file = files[0]

        if not file:
            return jsonify({
                "status": "error",
                "message": "Không tìm thấy tệp hình ảnh trong request."
            }), 400

        aspect_ratio = request.form.get('aspect_ratio', '3:4').strip()
        try:
            validate_batch_request([file], "crop", "3x4", "blue")
            img = normalize_input(file.stream)
            img_w, img_h = img.size
        except (BatchValidationError, ValueError, OSError) as e:
            return jsonify({
                "status": "error",
                "message": str(e) or "Không thể đọc tệp hình ảnh."
            }), 400

        face_bbox = detect_face(img)
        if not face_bbox:
            return jsonify({
                "status": "error",
                "message": "Không tìm thấy khuôn mặt trong ảnh, vui lòng tải ảnh rõ nét hơn."
            }), 400

        landmarks = get_face_landmarks(img)
        center_x = face_bbox[0] + face_bbox[2] / 2
        if landmarks and "center_nose" in landmarks:
            center_x = float(landmarks["center_nose"][0])

        final_x, final_y, final_w, final_h = calculate_face_crop_box(
            (img_w, img_h),
            face_bbox,
            aspect_ratio,
            center_x=center_x,
        )
        cropped_img = img.crop((final_x, final_y, final_x + final_w, final_y + final_h))
        session_id = str(uuid.uuid4())
        item_id = uuid.uuid4().hex[:8]
        asset = persist_photo_preview(
            cropped_img,
            session_id=session_id,
            owner_user_id=g.user_id,
            account_id=g.user.get("account_id") if hasattr(g, "user") and isinstance(g.user, dict) else None,
            item_id=item_id,
            kind="autocrop",
            original_filename=f"autocrop_{item_id}.jpg",
        )
        Log.info(
            f"[AUTO-CROP API] user={g.user_id} session={session_id} "
            f"ratio={aspect_ratio} input={img_w}x{img_h} "
            f"box={final_x},{final_y},{final_w},{final_h}"
        )
        return jsonify({
            "status": "success",
            "data": {
                "crop_box": {
                    "x": final_x,
                    "y": final_y,
                    "width": final_w,
                    "height": final_h
                },
                "confidence": None,
                "confidence_source": "not_available",
                "message": "Phát hiện khuôn mặt thành công",
                "session_id": session_id,
                "image_size": {"width": img_w, "height": img_h},
                "cropped_url": asset["url"],
                "url_expires_in_seconds": asset["url_expires_in_seconds"],
                "retention_expires_at": asset["retention_expires_at"],
            }
        }), 200

    except PhotoStorageError as e:
        Log.error(f"[AUTO-CROP API] Storage unavailable: {e}")
        return jsonify({"status": "error", "message": str(e)}), 503
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        Log.error(f"[AUTO-CROP API] Lỗi xử lý: {e}")
        import traceback
        Log.error(traceback.format_exc())
        return jsonify({
            "status": "error",
            "message": "Lỗi hệ thống khi xử lý ảnh. Vui lòng thử lại sau."
        }), 500
