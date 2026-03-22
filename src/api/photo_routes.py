import io
import cv2
import numpy as np
import uuid
import warnings

warnings.filterwarnings("ignore")

from flask import Blueprint, request, jsonify, send_file
from PIL import Image, ImageColor, ImageOps, ImageFilter

from src.utils.auth_middleware import require_auth
from src.utils.logger import Log

photo_bp = Blueprint('photo_routes', __name__)

PHOTO_SIZES = {
    '2x3': (236, 354),
    '3x4': (354, 472),
    '4x6': (472, 708)
}

BG_COLORS = {
    'blue':  '#0055ff',
    'white': '#ffffff',
    'red':   '#ff0000'
}

_MAX_INPUT_DIM = 1500

_CASCADE = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
)


def _normalize_input(stream) -> Image.Image:
    img = Image.open(stream)
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > _MAX_INPUT_DIM:
        scale = _MAX_INPUT_DIM / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    return img


def _detect_face(img_pil: Image.Image):
    """
    Detect mặt trên ảnh scale 2x để bắt được mặt nhỏ.
    Trả về (x, y, w, h) tọa độ gốc hoặc None.
    """
    w, h = img_pil.size
    cv_img = cv2.cvtColor(np.array(img_pil.convert("RGB")), cv2.COLOR_RGB2BGR)
    img2x  = cv2.resize(cv_img, (w * 2, h * 2), interpolation=cv2.INTER_LINEAR)
    gray2x = cv2.cvtColor(img2x, cv2.COLOR_BGR2GRAY)

    faces = _CASCADE.detectMultiScale(
        gray2x, scaleFactor=1.05, minNeighbors=4, minSize=(20, 20)
    )
    if len(faces) == 0:
        return None

    img_area = (w * 2) * (h * 2)
    faces = [f for f in faces if (f[2] * f[3]) > img_area * 0.01]
    if not faces:
        return None

    bx, by, bw, bh = max(faces, key=lambda f: f[2] * f[3])
    return bx // 2, by // 2, bw // 2, bh // 2


def _crop_portrait(no_bg_rgba: Image.Image, target_w: int, target_h: int) -> Image.Image | None:
    """
    Crop chuẩn ảnh thẻ, giữ đúng tỉ lệ target_w/target_h.

    Logic tính crop box:
      - Bắt đầu từ face_h: crop_h = face_h / 0.45 (mặt chiếm 45% chiều cao)
      - crop_w = crop_h * (target_w/target_h)  → giữ đúng tỉ lệ
      - Nếu crop_w < face_w * 1.8 (vai sẽ bị cắt):
          scale up từ crop_w = face_w * 1.8
          tính lại crop_h = crop_w / ratio       ← QUAN TRỌNG: luôn tính 1 chiều từ chiều kia
      - head_room = face_h * 0.8 phía trên bbox (Haar bbox bắt đầu từ trán, không phải tóc)

    Bug cũ: crop_w = max(fw*3.5, ratio_w) mà không tính lại crop_h
    → crop_w và crop_h độc lập → ratio sai tới 83%.
    """
    bbox = _detect_face(no_bg_rgba)
    if bbox is None:
        return None

    x, y, fw, fh = bbox
    img_w, img_h = no_bg_rgba.size
    ratio = target_w / target_h  # tỉ lệ cố định, ví dụ 354/472 = 0.75

    # Tính từ face_h
    crop_h = int(fh / 0.45)
    crop_w = int(crop_h * ratio)

    # Nếu crop_w không đủ rộng để chứa vai → scale up từ crop_w
    min_crop_w = int(fw * 1.8)
    if crop_w < min_crop_w:
        crop_w = min_crop_w
        crop_h = int(crop_w / ratio)  # tính lại crop_h để giữ đúng tỉ lệ

    cx = x + fw // 2
    x1 = cx - crop_w // 2
    y1 = y - int(fh * 0.8)   # head_room: bù phần tóc mà Haar không detect
    x2 = x1 + crop_w
    y2 = y1 + crop_h

    pad_l = max(0, -x1)
    pad_t = max(0, -y1)
    pad_r = max(0, x2 - img_w)
    pad_b = max(0, y2 - img_h)
    if any([pad_l, pad_t, pad_r, pad_b]):
        no_bg_rgba = ImageOps.expand(
            no_bg_rgba, border=(pad_l, pad_t, pad_r, pad_b), fill=(0, 0, 0, 0)
        )
        x1 += pad_l; y1 += pad_t
        x2 += pad_l; y2 += pad_t

    cropped = no_bg_rgba.crop((x1, y1, x2, y2))
    return cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)


def _smooth_alpha_edge(rgba: Image.Image, radius: float = 1.2) -> Image.Image:
    r, g, b, alpha = rgba.split()
    alpha = alpha.filter(ImageFilter.GaussianBlur(radius=radius))
    return Image.merge("RGBA", (r, g, b, alpha))


def _remove_color_spill(rgba: Image.Image, spill_color: str = "blue") -> Image.Image:
    arr = np.array(rgba, dtype=np.float32)
    r, g, b, a = arr[..., 0], arr[..., 1], arr[..., 2], arr[..., 3]
    edge = (a > 10) & (a < 245)
    if spill_color == "blue":
        spill = np.clip(b - (r + g) / 2, 0, None)
        arr[..., 2] = np.where(edge, np.clip(b - spill * 0.6, 0, 255), b)
    elif spill_color == "green":
        spill = np.clip(g - (r + b) / 2, 0, None)
        arr[..., 1] = np.where(edge, np.clip(g - spill * 0.6, 0, 255), g)
    elif spill_color == "red":
        spill = np.clip(r - (g + b) / 2, 0, None)
        arr[..., 0] = np.where(edge, np.clip(r - spill * 0.6, 0, 255), r)
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def _detect_source_bg_color(img_rgb: Image.Image) -> str:
    arr = np.array(img_rgb)
    h, w = arr.shape[:2]
    s = 20
    corners = np.concatenate([
        arr[:s, :s].reshape(-1, 3),
        arr[:s, w-s:].reshape(-1, 3),
        arr[h-s:, :s].reshape(-1, 3),
        arr[h-s:, w-s:].reshape(-1, 3),
    ])
    mean = corners.mean(axis=0)
    dominant = int(np.argmax(mean))
    if dominant == 2 and mean[2] > mean[0] * 1.3:
        return "blue"
    if dominant == 1 and mean[1] > mean[0] * 1.3:
        return "green"
    if dominant == 0 and mean[0] > mean[2] * 1.3:
        return "red"
    return "none"


@photo_bp.route("/api/photo/process", methods=["POST"])
@require_auth
def process_photo():
    try:
        if 'file' not in request.files:
            return jsonify({"statusCode": 400, "message": "No file part"}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({"statusCode": 400, "message": "No selected file"}), 400

        size_param     = request.form.get('size', '3x4')
        bg_color_param = request.form.get('bg_color', 'blue').lower()

        if size_param not in PHOTO_SIZES:
            return jsonify({"statusCode": 400,
                            "message": f"Invalid size. Allowed: {list(PHOTO_SIZES.keys())}"}), 400

        bg_hex = BG_COLORS.get(bg_color_param, bg_color_param)
        try:
            bg_rgba = ImageColor.getcolor(bg_hex, "RGBA")
        except ValueError:
            return jsonify({"statusCode": 400,
                            "message": f"Invalid bg_color: {bg_color_param}"}), 400

        target_w, target_h = PHOTO_SIZES[size_param]

        # 1. Normalize
        img_rgb = _normalize_input(file.stream)
        source_bg = _detect_source_bg_color(img_rgb)
        Log.info(f"Source bg: {source_bg}")

        # 2. rembg session
        try:
            from rembg import remove
            from src.models.model_loader import model_loader
            session = model_loader.rembg_session
            if not session:
                raise ImportError("rembg session not loaded")
        except ImportError:
            Log.error("rembg not available")
            return jsonify({"statusCode": 500, "message": "rembg error on server"}), 500

        # 3. Tách nền
        Log.info(f"Removing background: {file.filename}")
        no_bg_image = remove(img_rgb, session=session)
        if no_bg_image.mode != "RGBA":
            no_bg_image = no_bg_image.convert("RGBA")

        # 4. Khử color spill
        if source_bg != "none":
            no_bg_image = _remove_color_spill(no_bg_image, spill_color=source_bg)

        # 5. Smooth viền alpha
        no_bg_image = _smooth_alpha_edge(no_bg_image, radius=1.2)

        # 6. Crop đúng tỉ lệ theo mặt
        cropped_rgba = _crop_portrait(no_bg_image, target_w, target_h)
        if cropped_rgba is None:
            Log.warning(f"No face detected: {file.filename}")
            return jsonify({
                "statusCode": 422,
                "message": "Không tìm thấy khuôn mặt. Vui lòng chụp thẳng mặt, đủ sáng."
            }), 422

        # 7. Composite
        bg_image = Image.new("RGBA", (target_w, target_h), bg_rgba)
        bg_image.paste(cropped_rgba, (0, 0), mask=cropped_rgba.split()[3])

        # 8. Save
        final_image = bg_image.convert("RGB")
        img_byte_arr = io.BytesIO()
        final_image.save(img_byte_arr, format='JPEG', quality=95, dpi=(300, 300))
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