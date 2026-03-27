"""
Image Processing Utilities
Các hàm helper xử lý ảnh thẻ: normalize, face detection, crop, quality validation, encode.
"""
import io
import gc
import base64
import warnings

import cv2
import numpy as np
from PIL import Image, ImageColor, ImageOps, ImageFilter

warnings.filterwarnings("ignore")

# ─── Constants ────────────────────────────────────────────────────────────────

PHOTO_SIZES = {
    '2x3': (236, 354),
    '3x4': (354, 472),
    '4x6': (472, 708),
}

BG_COLORS = {
    'blue':  '#4ea2e5',
    'white': '#ffffff',
    'red':   '#ff0000',
}

_MAX_INPUT_DIM = 1500

_CASCADE = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_frontalface_default.xml" # type: ignore
)

_EYE_CASCADE = cv2.CascadeClassifier(
    cv2.data.haarcascades + "haarcascade_eye.xml" # type: ignore
)


# ─── Input Validation & Normalization ─────────────────────────────────────────

def normalize_input(stream) -> Image.Image:

    img = Image.open(stream)
    img = ImageOps.exif_transpose(img)
    if img.mode != "RGB":
        img = img.convert("RGB")
    w, h = img.size
    if max(w, h) > _MAX_INPUT_DIM:
        scale = _MAX_INPUT_DIM / max(w, h)
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    return img


def validate_image_size(img: Image.Image) -> list[str]:

    w, h = img.size
    warnings_list = []
    if w < 200 or h < 200:
        warnings_list.append(
            f"Ảnh có độ phân giải thấp ({w}x{h}px). "
            "Kết quả crop có thể bị vỡ nét. Vui lòng dùng ảnh chất lượng cao hơn."
        )
    return warnings_list


# ─── Face Detection & Alignment ───────────────────────────────────────────────

def align_face(img_pil: Image.Image) -> tuple[Image.Image, float]:
    """
    Tự động xoay thẳng khuôn mặt, kể cả khi ảnh gốc bị nghiêng nặng.
    1. Thử tìm mắt ở góc 0 độ.
    2. Nếu không thấy, thử xoay ảnh ở các góc khác nhau và tìm lại mắt.
    3. Tính toán góc xoay tổng hợp và xoay ảnh gốc một lần duy nhất.
    4. Cắt bỏ phần nền trong suốt thừa sau khi xoay.
    """
    img_rgba = img_pil.convert("RGBA")

    def _find_eyes_on_image(image: Image.Image) -> tuple[tuple[int, int], tuple[int, int]] | None:
        cv_img = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)
        faces = _CASCADE.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
        if len(faces) == 0:
            return None
        
        (x, y, w, h) = max(faces, key=lambda f: f[2] * f[3])
        roi_gray = gray[y:y+h, x:x+w]
        eyes = _EYE_CASCADE.detectMultiScale(roi_gray, scaleFactor=1.1, minNeighbors=10, minSize=(20, 20))
        
        if len(eyes) < 2:
            return None
            
        eyes = sorted(eyes, key=lambda e: e[0])
        eye1_center = (x + eyes[0][0] + eyes[0][2] // 2, y + eyes[0][1] + eyes[0][3] // 2)
        eye2_center = (x + eyes[1][0] + eyes[1][2] // 2, y + eyes[1][1] + eyes[1][3] // 2)
        return eye1_center, eye2_center

    # 1. Thử tìm mắt trên ảnh gốc
    final_angle = 0.0
    eye_coords = _find_eyes_on_image(img_pil)
    
    # 2. Nếu không thấy, thử xoay ảnh và tìm lại
    if eye_coords is None:
        for angle_offset in [25, -25, 40, -40]:
            rotated_pil = img_pil.rotate(angle_offset, expand=True)
            found_eyes = _find_eyes_on_image(rotated_pil)
            if found_eyes:
                # Tính góc nghiêng của mắt trên ảnh đã xoay
                dy = found_eyes[1][1] - found_eyes[0][1]
                dx = found_eyes[1][0] - found_eyes[0][0]
                if dx == 0: continue
                angle_on_rotated = float(np.degrees(np.arctan2(dy, dx)))
                # Góc nghiêng gốc của ảnh = góc đo được trên ảnh xoay - góc xoay tạm
                final_angle = angle_on_rotated - angle_offset
                break # Dừng lại khi đã tìm thấy
    else:
        # Tính góc nghiêng trên ảnh gốc
        dy = eye_coords[1][1] - eye_coords[0][1]
        dx = eye_coords[1][0] - eye_coords[0][0]
        if dx != 0:
            final_angle = float(np.degrees(np.arctan2(dy, dx)))

    # 3. Xoay ảnh gốc một lần duy nhất với góc tổng hợp
    if abs(final_angle) < 0.5:
        return img_pil, 0.0

    rotated_rgba = img_rgba.rotate(-final_angle, resample=Image.Resampling.BICUBIC, expand=True)
    
    # 4. Cắt bỏ phần trong suốt dư thừa
    rotated_cv = cv2.cvtColor(np.array(rotated_rgba), cv2.COLOR_RGBA2BGRA)
    alpha_channel = rotated_cv[:, :, 3]
    _, mask = cv2.threshold(alpha_channel, 1, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if contours:
        all_points = np.concatenate(contours)
        x, y, w, h = cv2.boundingRect(all_points)
        rotated_rgba = rotated_rgba.crop((x, y, x + w, y + h))
    
    return rotated_rgba.convert("RGB"), final_angle


def detect_face(img_pil: Image.Image) -> tuple[int, int, int, int] | None:
    """
    Phát hiện khuôn mặt lớn nhất. 
    Hỗ trợ thử xoay ảnh nếu không tìm thấy ở góc mặc định (cho ảnh chụp nghiêng).
    """
    cv_img = cv2.cvtColor(np.array(img_pil.convert("RGB")), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

    def _try_detect(image):
        faces = _CASCADE.detectMultiScale(image, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
        if len(faces) > 0:
            return max(faces, key=lambda f: f[2] * f[3])
        return None

    # Thử góc 0 độ
    face = _try_detect(gray)
    if face is not None:
        return tuple(face.tolist()) # type: ignore

    # Nếu không thấy, thử xoay nhẹ sang trái/phải 20 độ (trường hợp người dùng up ảnh nghiêng sẵn)
    rows, cols = gray.shape
    for angle in [20, -20, 35, -35]:
        M = cv2.getRotationMatrix2D((cols/2, rows/2), angle, 1)
        rotated_gray = cv2.warpAffine(gray, M, (cols, rows))
        face = _try_detect(rotated_gray)
        if face is not None:
            # Lưu ý: Trả về face ở góc này chỉ để biết là CÓ mặt, 
            # align_face sẽ lo việc xoay chuẩn dựa trên mắt sau.
            return tuple(face.tolist()) # type: ignore

    return None


# ─── Quality Validation ───────────────────────────────────────────────────────

def validate_photo_quality(img_pil: Image.Image, face_bbox) -> list[str]:
    """
    Kiểm tra các yếu tố chất lượng ảnh quan trọng để đảm bảo ảnh thẻ tốt nhất.
    """
    quality_warnings: list[str] = []
    w, h = img_pil.size
    gray = cv2.cvtColor(np.array(img_pil.convert("L")), cv2.COLOR_GRAY2BGR)

    if face_bbox:
        fx, fy, fw, fh = face_bbox

        # 1. Kiểm tra đôi mắt để đảm bảo ảnh chính diện
        face_roi = gray[fy:fy+fh, fx:fx+fw]
        eyes = _EYE_CASCADE.detectMultiScale(face_roi, scaleFactor=1.1, minNeighbors=10, minSize=(20, 20))
        if len(eyes) < 2:
            quality_warnings.append(
                "Không nhìn rõ hai mắt. Vui lòng nhìn thẳng, không đeo kính râm và không để tóc che mắt."
            )

        # 2. Kiểm tra kích thước & vị trí khuôn mặt
        face_area_ratio = (fw * fh) / (w * h)
        if face_area_ratio < 0.03:
            quality_warnings.append("Khuôn mặt quá nhỏ trong ảnh. Vui lòng đứng gần camera hơn.")

        if fy < h * 0.05:
            quality_warnings.append("Đỉnh đầu quá sát mép trên. Vui lòng chừa thêm khoảng trống phía trên đầu.")

    return quality_warnings


# ─── Crop Functions ───────────────────────────────────────────────────────────

def crop_portrait_rgb(
    img_rgb: Image.Image, 
    face_bbox: tuple[int, int, int, int],
    target_w: int, 
    target_h: int
) -> Image.Image | None:
    """
    [TYPE=CROP] Crop chuẩn ảnh thẻ trực tiếp từ ảnh RGB gốc (không cần tách nền).
    Dùng heuristic dựa trên face_bbox để tính crop box, thay vì getbbox() alpha.
    Padding bằng màu xám trắng nếu crop box vượt ra ngoài ảnh.
    Trả về Image đã resize về (target_w, target_h) hoặc None nếu thất bại.
    """
    if face_bbox is None:
        return None

    img_w, img_h = img_rgb.size
    fx, fy, fw, fh = face_bbox
    ratio = target_w / target_h

    # 1. Tính crop_h dựa trên tỉ lệ mặt chiếm ~40% chiều cao ảnh thẻ (tăng từ 45% để crop sát hơn)
    crop_h = int(fh / 0.40)
    crop_w = int(crop_h * ratio)

    # 2. Đảm bảo chiều rộng lấy được vai (tối thiểu 2.2x fw, giảm từ 2.5x để crop sát hơn)
    min_crop_w = int(fw * 2.2)
    if crop_w < min_crop_w:
        crop_w = min_crop_w
        crop_h = int(crop_w / ratio)

    # 3. Tâm ngang khuôn mặt
    cx = fx + fw // 2

    # 4. LUÔN LUÔN CĂN SÁT ĐÁY
    # Đặt cạnh dưới của crop box (y2) bằng cạnh dưới của ảnh gốc (img_h)
    y2 = img_h
    # Tính ngược y1 từ y2 để giữ đúng tỉ lệ
    y1 = y2 - crop_h

    # Đặt x1 dựa trên tâm cx
    x1 = cx - crop_w // 2
    x2 = x1 + crop_w

    # 5. Xử lý crop box vượt biên → Padding màu xám sáng
    pad_l = max(0, -x1)
    pad_t = max(0, -y1)
    pad_r = max(0, x2 - img_w)
    # pad_b sẽ luôn bằng 0 vì y2=img_h
    pad_b = max(0, y2 - img_h)

    PADDING_COLOR = (240, 240, 240)  # Xám sáng

    if any([pad_l, pad_t, pad_r, pad_b]):
        img_rgb = ImageOps.expand(
            img_rgb, border=(pad_l, pad_t, pad_r, pad_b), fill=PADDING_COLOR
        )
        x1 += pad_l; y1 += pad_t
        x2 += pad_l; y2 += pad_t

    # 7. Cắt và resize
    cropped = img_rgb.crop((x1, y1, x2, y2))
    return cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)


def crop_portrait_rgba(
    no_bg_rgba: Image.Image,
    target_w: int,
    target_h: int
) -> Image.Image | None:
    """
    [TYPE=FULL] Crop chuẩn ảnh thẻ từ ảnh RGBA đã tách nền.
    Dùng getbbox() để tìm viền người qua alpha channel.
    Trả về Image RGBA đã resize hoặc None nếu không tìm thấy mặt.
    """
    bbox = detect_face(no_bg_rgba)
    if bbox is None:
        return None

    x, y, fw, fh = bbox
    img_w, img_h = no_bg_rgba.size
    ratio = target_w / target_h

    crop_h = int(fh / 0.45)
    crop_w = int(crop_h * ratio)

    min_crop_w = int(fw * 2.5)
    if crop_w < min_crop_w:
        crop_w = min_crop_w
        crop_h = int(crop_w / ratio)

    cx = x + fw // 2
    head_room = int(crop_h * 0.12)
    y_top_head = y - int(fh * 0.25)
    y1 = y_top_head - head_room
    x1 = cx - crop_w // 2
    x2 = x1 + crop_w
    y2 = y1 + crop_h

    # Auto-fit width bằng actual bbox (alpha channel)
    actual_bbox = no_bg_rgba.getbbox()
    if actual_bbox:
        person_l, person_t, person_r, person_b = actual_bbox
        person_w = person_r - person_l
        ideal_crop_w = int(person_w / 0.99)
        max_w = int(fw * 4.5)
        min_w = int(fw * 2.2)
        ideal_crop_w = max(min_w, min(max_w, ideal_crop_w))
        crop_w = ideal_crop_w
        crop_h = int(crop_w / ratio)
        x1 = cx - crop_w // 2
        x2 = x1 + crop_w
        y2 = person_b
        y1 = y2 - crop_h

    pad_l = max(0, -x1)
    pad_t = max(0, -y1)
    pad_r = max(0, x2 - img_w)
    pad_b = 0

    if any([pad_l, pad_t, pad_r, pad_b]):
        no_bg_rgba = ImageOps.expand(
            no_bg_rgba, border=(pad_l, pad_t, pad_r, pad_b), fill=(0, 0, 0, 0)
        )
        x1 += pad_l; y1 += pad_t
        x2 += pad_l; y2 += pad_t

    cropped = no_bg_rgba.crop((x1, y1, x2, y2))
    return cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)


# ─── Background Removal Helpers ───────────────────────────────────────────────

def detect_source_bg_color(img_rgb: Image.Image) -> str:
    """
    Đoán màu nền gốc bằng cách lấy mẫu 4 góc ảnh.
    Cần phát hiện trước khi tách nền để khử spill đúng kênh.
    """
    arr = np.array(img_rgb)
    h, w = arr.shape[:2]
    s = 20
    corners = np.concatenate([
        arr[:s,   :s ].reshape(-1, 3),
        arr[:s,  w-s:].reshape(-1, 3),
        arr[h-s:,  :s].reshape(-1, 3),
        arr[h-s:, w-s:].reshape(-1, 3),
    ])
    mean = corners.mean(axis=0)

    if all(c > 200 for c in mean) and max(mean) - min(mean) < 30:
        return "white"
    dominant = int(np.argmax(mean))
    if dominant == 2 and mean[2] > mean[0] * 1.3:
        return "blue"
    if dominant == 1 and mean[1] > mean[0] * 1.3:
        return "green"
    if dominant == 0 and mean[0] > mean[2] * 1.3:
        return "red"
    return "none"


def remove_color_spill(rgba: Image.Image, spill_color: str) -> Image.Image:
    """
    Khử color spill — màu nền gốc thấm vào pixel RGB vùng viền.
    Chỉ xử lý vùng bán trong suốt (alpha 10–245).
    """
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


def refine_alpha_edge(rgba: Image.Image, source_bg: str = "none") -> Image.Image:
    """
    Làm mịn viền alpha sau khi tách nền.
    """
    r, g, b, alpha = rgba.split()
    alpha_np = np.array(alpha, dtype=np.uint8)

    if source_bg == "white":
        _, alpha_np = cv2.threshold(alpha_np, 120, 255, cv2.THRESH_BINARY)
        alpha_blurred = cv2.GaussianBlur(alpha_np, (3, 3), sigmaX=0.8)
    else:
        kernel = np.ones((3, 3), np.uint8)
        alpha_eroded  = cv2.erode(alpha_np, kernel, iterations=1)
        alpha_blurred = cv2.GaussianBlur(alpha_eroded, (3, 3), sigmaX=1.2)

    return Image.merge("RGBA", (r, g, b, Image.fromarray(alpha_blurred)))


# ─── Encode Helpers ───────────────────────────────────────────────────────────

def image_to_base64(img: Image.Image, fmt: str = "JPEG") -> str:
    """
    Encode PIL Image → base64 string.
    fmt: 'JPEG' hoặc 'PNG'
    JPEG: DPI=300 để đảm bảo in đúng kích thước vật lý.
    """
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(buf, format="JPEG", quality=95, dpi=(300, 300))
    else:
        img.save(buf, format="PNG")
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")


def build_file_object(
    img: Image.Image,
    filename: str,
    fmt: str = "JPEG"
) -> dict:
    """
    Build object chứa thông tin file để trả về trong response.
    """
    mimetype = "image/jpeg" if fmt == "JPEG" else "image/png"
    return {
        "filename": filename,
        "mimetype": mimetype,
        "data": image_to_base64(img, fmt),
    }
