import os
import io
from flask import Blueprint, request, jsonify, send_file, g
from werkzeug.utils import secure_filename
from PIL import Image, ImageColor
import uuid

# Mute warnings from rembg if any
import warnings
warnings.filterwarnings("ignore")

from src.utils.auth_middleware import require_auth
from src.utils.logger import Log

photo_bp = Blueprint('photo_routes', __name__)

# Kích thước chuẩn ảnh thẻ (pixels) ở 300 DPI (approx)
# 2x3: 20x30 mm -> ~236x354 px
# 3x4: 30x40 mm -> ~354x472 px
# 4x6: 40x60 mm -> ~472x708 px
PHOTO_SIZES = {
    '2x3': (236, 354),
    '3x4': (354, 472),
    '4x6': (472, 708)
}

# Mapping màu chuẩn cho ảnh thẻ
BG_COLORS = {
    'blue': '#0055ff', # xanh dương
    'white': '#ffffff', # trắng
    'red': '#ff0000' # đỏ
}

@photo_bp.route("/api/photo/process", methods=["POST"])
@require_auth
def process_photo():
    try:
        if 'file' not in request.files:
            return jsonify({"statusCode": 400, "message": "No file part"}), 400
            
        file = request.files['file']
        if file.filename == '':
            return jsonify({"statusCode": 400, "message": "No selected file"}), 400

        # Lấy tham số cấu hình
        size_param = request.form.get('size', '3x4')
        bg_color_param = request.form.get('bg_color', 'blue').lower()

        # Validate tham số
        if size_param not in PHOTO_SIZES:
            return jsonify({"statusCode": 400, "message": f"Invalid size. Allowed: {list(PHOTO_SIZES.keys())}"}), 400

        # Xử lý màu sắc
        # Có thể là tên màu (blue, white) hoặc mã hex (#123456)
        bg_hex = BG_COLORS.get(bg_color_param, bg_color_param)
        try:
            bg_rgba = ImageColor.getcolor(bg_hex, "RGBA")
        except ValueError:
            return jsonify({"statusCode": 400, "message": f"Invalid bg_color: {bg_color_param}"}), 400

        target_w, target_h = PHOTO_SIZES[size_param]

        # Đọc ảnh
        input_image = Image.open(file.stream).convert("RGBA")

        # Lấy rembg session từ model_loader
        try:
            from rembg import remove
            from src.models.model_loader import model_loader
            session = model_loader.rembg_session
            if not session:
                raise ImportError("Failed to load rembg session")
        except ImportError:
            Log.error("rembg is not installed or loaded properly. Please run: pip install rembg[cpu]")
            return jsonify({"statusCode": 500, "message": "rembg error on server"}), 500

        # 1. Tách nền ảnh
        Log.info(f"Removing background for file: {file.filename}")
        no_bg_image = remove(input_image, session=session)

        # 2. Tạo hình đệm (background mới)
        bg_image = Image.new("RGBA", (target_w, target_h), bg_rgba)

        # 3. Tính toán kích thước ảnh chân dung để resize (Fit/Crop logic)
        # Thông thường ảnh thẻ tập trung vào khuôn mặt. 
        # Chúng ta sẽ resize ảnh đã tách nền sao cho chiều cao của nó fit với target
        # hoặc có thể dùng phương pháp scale aspect ratio.
        orig_w, orig_h = no_bg_image.size
        
        # Scale no_bg_image to fill the target height (hoặc width nếu to quá)
        # Thực tế ảnh chụp người có thể đã crop, ta sẽ giữ nguyên aspect ratio, 
        # fit the height to 90% of target_h (chừa lề trên 1 chút)
        
        scale = (target_h * 0.95) / orig_h
        new_w = int(orig_w * scale)
        new_h = int(orig_h * scale)
        
        # Nếu chiều rộng vượt quá target_w, dùng target_w làm scale
        if new_w > target_w:
            scale = target_w / orig_w
            new_w = int(orig_w * scale)
            new_h = int(orig_h * scale)

        resized_person = no_bg_image.resize((new_w, new_h), Image.LANCZOS)

        # 4. Tính toán vị trí dán (Căn giữa theo chiều ngang, sát đáy)
        paste_x = (target_w - new_w) // 2
        paste_y = target_h - new_h # Align bottom
        
        # 5. Dán ảnh chân dung lên nền mới (sử dụng alpha mask)
        bg_image.paste(resized_person, (paste_x, paste_y), mask=resized_person)

        # Convert to RGB to save as JPG
        final_image = bg_image.convert("RGB")

        # Lưu vào vùng đệm RAM và gửi về trực tiếp
        img_byte_arr = io.BytesIO()
        final_image.save(img_byte_arr, format='JPEG', quality=95)
        img_byte_arr.seek(0)
        
        out_filename = f"photo_{size_param}_{uuid.uuid4().hex[:8]}.jpg"

        return send_file(
            img_byte_arr,
            mimetype='image/jpeg',
            as_attachment=True,
            download_name=out_filename
        )

    except Exception as e:
        Log.error(f"[PHOTO API] Error: {e}")
        import traceback
        Log.error(traceback.format_exc())
        return jsonify({"statusCode": 500, "message": str(e)}), 500
