"""
Photo Routes — API Endpoint xử lý ảnh thẻ.
Route handler thuần túy: validate request → gọi service → trả response.
"""
from flask import Blueprint, request, jsonify

from src.utils.auth_middleware import require_auth
from src.utils.logger import Log
from src.services.photo_service import (
    validate_batch_request,
    process_batch,
    BatchValidationError,
)

photo_bp = Blueprint('photo_routes', __name__)


@photo_bp.route("/api/photo/process", methods=["POST"])
@require_auth
def process_photo():
    
    try:
        # ── 1. Lấy danh sách file ─────────────────────────────────────────────
        files = request.files.getlist('files')

        # Hỗ trợ backward-compatible: nếu client gửi 'file' (single) thay vì 'files'
        if not files:
            single = request.files.get('file')
            if single:
                files = [single]

        # ── 2. Lấy params ─────────────────────────────────────────────────────
        process_type    = request.form.get('type', 'crop').lower().strip()
        size_param      = request.form.get('size', '3x4').strip()
        bg_color_param  = request.form.get('bg_color', 'blue').lower().strip()
        ignore_warnings = request.form.get('ignore_warnings', 'false').lower() == 'true'

        Log.info(
            f"[PHOTO API] Request: type={process_type}, size={size_param}, "
            f"bg_color={bg_color_param}, files={len(files)}, ignore_warnings={ignore_warnings}"
        )

        # ── 3. Validate batch (fail fast, không tốn CPU) ──────────────────────
        try:
            validate_batch_request(files, process_type, size_param, bg_color_param)
        except BatchValidationError as e:
            return jsonify({"statusCode": 400, "message": str(e)}), 400

        # ── 4. Xử lý batch ────────────────────────────────────────────────────
        results = process_batch(
            files         = files,
            process_type  = process_type,
            size_param    = size_param,
            bg_color_param= bg_color_param,
            ignore_warnings = ignore_warnings,
        )

        # ── 5. Build summary & Full URLs ──────────────────────────────────────
        total   = len(results)
        success = sum(1 for r in results if r["status"] == "success")
        failed  = total - success

        # Chuyển đổi path tương đối thành Full URL
        base_url = request.host_url.rstrip('/')
        for r in results:
            if r.get("original_url"):
                r["original_url"] = base_url + r["original_url"]
            if r.get("cropped_url"):
                r["cropped_url"] = base_url + r["cropped_url"]

        return jsonify({
            "statusCode": 200,
            "type":       process_type,
            "size":       size_param,
            "total":      total,
            "success":    success,
            "failed":     failed,
            "results":    results,
        }), 200

    except Exception as e:
        Log.error(f"[PHOTO API] Unhandled error: {e}")
        import traceback
        Log.error(traceback.format_exc())
        return jsonify({"statusCode": 500, "message": "Lỗi hệ thống. Vui lòng thử lại."}), 500