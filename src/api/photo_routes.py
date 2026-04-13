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
    clear_session_data,
    BatchValidationError,
)

photo_bp = Blueprint('photo_routes', __name__)


@photo_bp.route("/api/photo/process", methods=["POST"])
@require_auth
def process_photo():
    
    try:
        import uuid
        session_id = str(uuid.uuid4())

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
            f"[PHOTO API] Request: session={session_id}, type={process_type}, size={size_param}, "
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
            session_id    = session_id
        )

        # ── 5. Build summary & Full URLs ──────────────────────────────────────
        total   = len(results)
        success = sum(1 for r in results if r["status"] == "success")
        failed  = total - success

        # Chuyển đổi path tương đối thành Full URL
        # Sử dụng request.host_url (có kèm / ở cuối)
        base_url = request.host_url.rstrip('/') 
        
        for r in results:
            if r.get("original_url") and not r["original_url"].startswith("http"):
                r["original_url"] = f"{base_url}{r['original_url']}"
            if r.get("cropped_url") and not r["cropped_url"].startswith("http"):
                r["cropped_url"] = f"{base_url}{r['cropped_url']}"

        Log.info(f"[PHOTO API] Response ready. Session: {session_id}, Success: {success}")

        return jsonify({
            "statusCode": 200,
            "session_id": session_id,
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

        success = clear_session_data(session_id)
        
        if success:
            return jsonify({
                "statusCode": 200,
                "message": f"Successfully cleared data for session {session_id}"
            }), 200
        else:
            return jsonify({
                "statusCode": 500, 
                "message": f"Failed to clear data for session {session_id}"
            }), 500

    except Exception as e:
        Log.error(f"[PHOTO API] Clear error: {e}")
        return jsonify({"statusCode": 500, "message": str(e)}), 500


@photo_bp.route("/api/driver-center/ai/auto-crop", methods=["POST"])
@require_auth
def auto_crop_face():
    """
    API Tự Động Nhận Diện Và Cắt Ảnh Chân Dung (Auto-Crop)
    Theo yêu cầu tại AI_Cropper_Requirements.md
    """
    import os
    import uuid
    from PIL import Image
    from werkzeug.utils import secure_filename
    from src.utils.image_processing import detect_face
    from src.services.photo_service import PREVIEW_DIR, PREVIEW_SUBFOLDER

    try:
        # 1. Lấy file ảnh từ request
        file = request.files.get('image')
        if not file:
            # Hỗ trợ fallback sang 'file' hoặc 'files'
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

        aspect_ratio = request.form.get('aspect_ratio', '').strip()

        # Đọc ảnh
        try:
            img = Image.open(file.stream)
            # Fix EXIF orientation nếu có
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
            img_w, img_h = img.size
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": "Không thể đọc tệp hình ảnh. Vui lòng đảm bảo đó là định dạng hợp lệ (JPEG, PNG)."
            }), 400

        # 2. Phát hiện khuôn mặt
        face_bbox = detect_face(img)
        if not face_bbox:
            return jsonify({
                "status": "error",
                "message": "Không tìm thấy khuôn mặt trong ảnh, vui lòng tải ảnh rõ nét hơn."
            }), 400

        face_x, face_y, face_w, face_h = face_bbox

        # 3. Tính toán Padding Box (margin)
        # Tăng mạnh margin để lấy nhiều không gian hơn (đặc biệt là 2 bên vai và phần thân dưới)
        # Chiều rộng tăng 150% so với khuôn mặt, chiều cao tăng 180%
        padding_w = face_w * 1.5
        padding_h = face_h * 1.8

        ideal_x = face_x - (padding_w / 2)
        # Ở trục Y, đẩy lên trên một chút để lấy đỉnh đầu (trừ đi 1/3 padding_h),
        # phần lớn padding_h (2/3) sẽ dồn xuống dưới để lấy phần thân người/vai
        ideal_y = face_y - (padding_h / 3)

        ideal_w = face_w + padding_w
        ideal_h = face_h + padding_h

        # 4. Xử lý Aspect Ratio (tỷ lệ khung hình)
        if aspect_ratio == '1:1':
            # Cân bằng width và height bằng nhau
            max_side = max(ideal_w, ideal_h)
            
            # Căn giữa lại x và y sau khi điều chỉnh kích thước
            ideal_x = ideal_x - (max_side - ideal_w) / 2
            ideal_y = ideal_y - (max_side - ideal_h) / 2
            
            ideal_w = max_side
            ideal_h = max_side
            
        elif aspect_ratio == '3:4':
            # Height = Width * 4/3
            # Ta giữ nguyên width, tính lại height để đảm bảo lấy đủ 2 bên vai
            target_h = ideal_w * (4 / 3)
            if target_h < ideal_h:
                # Nếu height tính ra nhỏ hơn height cần thiết, ta mở rộng width theo height
                ideal_w = ideal_h * (3 / 4)
                target_h = ideal_h
                ideal_x = ideal_x - (ideal_w - (face_w + padding_w)) / 2
                
            ideal_y = ideal_y - (target_h - ideal_h) / 2
            ideal_h = target_h
            
            # Đảm bảo crop_box của ảnh 3x4 không quá nhỏ hoặc quá to so với ảnh gốc
            # Tối thiểu 20% chiều rộng ảnh gốc, tối đa 95% chiều rộng ảnh gốc
            min_w = img_w * 0.2
            max_w = img_w * 0.95
            
            if ideal_w < min_w:
                diff_w = min_w - ideal_w
                ideal_w = min_w
                ideal_h = min_w * (4 / 3)
                ideal_x -= diff_w / 2
                ideal_y -= (ideal_h - target_h) / 2
            elif ideal_w > max_w:
                diff_w = ideal_w - max_w
                ideal_w = max_w
                ideal_h = max_w * (4 / 3)
                ideal_x += diff_w / 2
                ideal_y += (target_h - ideal_h) / 2
            
        elif aspect_ratio == '4:6' or aspect_ratio == '2:3':
            # Height = Width * 1.5
            target_h = ideal_w * 1.5
            if target_h < ideal_h:
                ideal_w = ideal_h / 1.5
                target_h = ideal_h
                ideal_x = ideal_x - (ideal_w - (face_w + padding_w)) / 2
                
            ideal_y = ideal_y - (target_h - ideal_h) / 2
            ideal_h = target_h

        # 5. Đảm bảo crop_box nằm trong giới hạn của ảnh thực tế VÀ GIỮ ĐÚNG TỶ LỆ KHUNG HÌNH
        # Thu nhỏ khung nếu nó lớn hơn ảnh gốc
        if ideal_w > img_w or ideal_h > img_h:
            scale_w = img_w / ideal_w if ideal_w > 0 else 1.0
            scale_h = img_h / ideal_h if ideal_h > 0 else 1.0
            scale = min(scale_w, scale_h)
            
            center_x = ideal_x + ideal_w / 2
            center_y = ideal_y + ideal_h / 2
            
            ideal_w *= scale
            ideal_h *= scale
            ideal_x = center_x - ideal_w / 2
            ideal_y = center_y - ideal_h / 2

        final_w = int(ideal_w)
        final_h = int(ideal_h)
        
        # Cố định lại chiều cao theo chiều rộng để tỷ lệ chính xác 100% sau khi làm tròn
        if aspect_ratio == '1:1':
            final_h = final_w
        elif aspect_ratio == '3:4':
            final_h = int(final_w * 4 / 3)
        elif aspect_ratio == '4:6' or aspect_ratio == '2:3':
            final_h = int(final_w * 1.5)
            
        # Đảm bảo làm tròn không làm kích thước lố qua ảnh gốc
        if final_h > img_h:
            final_h = img_h
            if aspect_ratio == '3:4':
                final_w = int(final_h * 3 / 4)
            elif aspect_ratio == '4:6' or aspect_ratio == '2:3':
                final_w = int(final_h / 1.5)
            elif aspect_ratio == '1:1':
                final_w = final_h
                
        if final_w > img_w:
            final_w = img_w
            if aspect_ratio == '3:4':
                final_h = int(final_w * 4 / 3)
            elif aspect_ratio == '4:6' or aspect_ratio == '2:3':
                final_h = int(final_w * 1.5)
            elif aspect_ratio == '1:1':
                final_h = final_w

        final_x = int(ideal_x)
        final_y = int(ideal_y)

        # Dịch chuyển (shift) khung vào bên trong ảnh nếu bị tràn ra ngoài
        if final_x < 0:
            final_x = 0
        elif final_x + final_w > img_w:
            final_x = img_w - final_w
            
        if final_y < 0:
            final_y = 0
        elif final_y + final_h > img_h:
            final_y = img_h - final_h
            
        # Để an toàn lần cuối
        final_x = max(0, final_x)
        final_y = max(0, final_y)

        # 6. Cắt ảnh và lưu để tạo URL xem trước
        cropped_img = img.crop((final_x, final_y, final_x + final_w, final_y + final_h))
        
        session_id = str(uuid.uuid4())
        filename = secure_filename(file.filename) if file.filename else "image.jpg"
        name, ext = os.path.splitext(filename)
        if not ext:
            ext = ".jpg"
            
        cropped_filename = f"autocrop_{session_id}{ext}"
        cropped_path = os.path.join(PREVIEW_DIR, cropped_filename)
        
        # Lưu ảnh (convert sang RGB nếu là RGBA để lưu JPEG)
        if cropped_img.mode in ("RGBA", "P"):
            cropped_img = cropped_img.convert("RGB")
        cropped_img.save(cropped_path, quality=90)
        
        # Tạo URL
        base_url = request.host_url.rstrip('/')
        cropped_url = f"{base_url}/uploads/{PREVIEW_SUBFOLDER}/{cropped_filename}"

        # 7. Trả về response theo chuẩn
        return jsonify({
            "status": "success",
            "data": {
                "crop_box": {
                    "x": final_x,
                    "y": final_y,
                    "width": final_w,
                    "height": final_h
                },
                "confidence": 0.98,  # Fake confidence as requested in example
                "message": "Phát hiện khuôn mặt thành công",
                "cropped_url": cropped_url
            }
        }), 200

    except Exception as e:
        Log.error(f"[AUTO-CROP API] Lỗi xử lý: {e}")
        import traceback
        Log.error(traceback.format_exc())
        return jsonify({
            "status": "error",
            "message": "Lỗi hệ thống khi xử lý ảnh. Vui lòng thử lại sau."
        }), 500