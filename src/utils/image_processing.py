
import io
import gc
import base64
import warnings
import threading

import cv2
import numpy as np
from PIL import Image, ImageColor, ImageOps, ImageFilter
from src.config import (
    PHOTO_FACE_ROLL_AUTO_ALIGN_DEGREES,
    PHOTO_FACE_ROLL_WARN_DEGREES,
)

_FACE_ANALYZER = None
_FACE_ANALYZER_FAILED = False
_FACE_ANALYZER_LOCK = threading.Lock()
MAX_INPUT_PIXELS = 25_000_000
ALLOWED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "BMP"}

def get_face_analyzer():
    """Lazy load InsightFace FaceAnalysis."""
    global _FACE_ANALYZER, _FACE_ANALYZER_FAILED
    if _FACE_ANALYZER_FAILED:
        return None
    if _FACE_ANALYZER is None:
        with _FACE_ANALYZER_LOCK:
            if _FACE_ANALYZER is not None:
                return _FACE_ANALYZER
            if _FACE_ANALYZER_FAILED:
                return None
            try:
                from insightface.app import FaceAnalysis
                _FACE_ANALYZER = FaceAnalysis(
                    name="buffalo_sc",
                    allowed_modules=["detection"],
                    providers=["CPUExecutionProvider"],
                )
                _FACE_ANALYZER.prepare(ctx_id=0, det_thresh=0.5, det_size=(640, 640))
            except Exception as e:
                from src.utils.logger import Log
                _FACE_ANALYZER_FAILED = True
                Log.error(f"[PHOTO MODEL] InsightFace unavailable, using Haar fallback: {e}")
                return None
    return _FACE_ANALYZER

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
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            img = Image.open(stream)
            if img.format not in ALLOWED_IMAGE_FORMATS:
                raise UnidentifiedImageError(
                    f"Định dạng ảnh không được hỗ trợ: {img.format or 'unknown'}."
                )
            w, h = img.size
            if w <= 0 or h <= 0 or w * h > MAX_INPUT_PIXELS:
                raise ValueError(
                    f"Ảnh vượt giới hạn {MAX_INPUT_PIXELS:,} pixels hoặc kích thước không hợp lệ."
                )
            img.load()
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as e:
        raise ValueError(
            f"Ảnh vượt giới hạn an toàn {MAX_INPUT_PIXELS:,} pixels."
        ) from e
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

FACE_ROLL_MIN_DEGREES = 0.5
FACE_ROLL_WARN_DEGREES = PHOTO_FACE_ROLL_WARN_DEGREES
FACE_ROLL_AUTO_ALIGN_DEGREES = PHOTO_FACE_ROLL_AUTO_ALIGN_DEGREES


def estimate_face_roll(landmarks: dict) -> tuple[float, dict]:
    """
    Ước lượng face roll bằng median của trục mắt, khóe miệng và trục dọc mặt.
    Median giảm ảnh hưởng của makeup, mắt không cân hoặc nụ cười lệch.
    """
    components: dict[str, float] = {}

    def _line_angle(left, right) -> float | None:
        dx = float(right[0]) - float(left[0])
        dy = float(right[1]) - float(left[1])
        if abs(dx) < 1e-6:
            return None
        return float(np.degrees(np.arctan2(dy, dx)))

    left_eye = landmarks.get("left_eye")
    right_eye = landmarks.get("right_eye")
    left_mouth = landmarks.get("left_mouth")
    right_mouth = landmarks.get("right_mouth")

    if left_eye is not None and right_eye is not None:
        eye_angle = _line_angle(left_eye, right_eye)
        if eye_angle is not None:
            components["eyes"] = eye_angle

    if left_mouth is not None and right_mouth is not None:
        mouth_angle = _line_angle(left_mouth, right_mouth)
        if mouth_angle is not None:
            components["mouth"] = mouth_angle

    if all(point is not None for point in (left_eye, right_eye, left_mouth, right_mouth)):
        eye_mid_x = (float(left_eye[0]) + float(right_eye[0])) / 2
        eye_mid_y = (float(left_eye[1]) + float(right_eye[1])) / 2
        mouth_mid_x = (float(left_mouth[0]) + float(right_mouth[0])) / 2
        mouth_mid_y = (float(left_mouth[1]) + float(right_mouth[1])) / 2
        vertical_dx = mouth_mid_x - eye_mid_x
        vertical_dy = mouth_mid_y - eye_mid_y
        if vertical_dy > 1e-6:
            components["face_axis"] = float(
                np.degrees(np.arctan2(-vertical_dx, vertical_dy))
            )

    if not components:
        return 0.0, {}

    # Trục mắt của InsightFace là anchor; mouth/face-axis chỉ tham gia khi đồng thuận.
    # Điều này tránh yaw hoặc nụ cười lệch kéo sai kết quả roll.
    anchor = components.get("eyes", float(np.median(list(components.values()))))
    consistent = {
        name: angle
        for name, angle in components.items()
        if abs(angle - anchor) <= 8.0
    }
    selected = consistent or components
    return float(np.median(list(selected.values()))), components


def align_face(
    img_pil: Image.Image,
    force_align: bool = False,
) -> tuple[Image.Image, dict]:
    """
    Đo face roll, chỉ tự xoay khi |roll| >= 8° hoặc client force_align.
    Trả metadata để client phân biệt face roll với độ nghiêng của toàn ảnh.
    """

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

    # 1. Ưu tiên multi-landmark InsightFace, fallback Haar nếu không khả dụng.
    final_angle = 0.0
    angle_components: dict[str, float] = {}
    detector = "none"
    landmarks = get_face_landmarks(img_pil)
    if landmarks and "left_eye" in landmarks and "right_eye" in landmarks:
        final_angle, angle_components = estimate_face_roll(landmarks)
        detector = "insightface"
        eye_coords = None
    else:
        eye_coords = _find_eyes_on_image(img_pil)
        detector = "haar" if eye_coords else "none"

    # 2. Nếu không thấy, thử xoay ảnh và tìm lại
    if detector == "none":
        for angle_offset in [25, -25, 40, -40]:
            rotated_pil = img_pil.rotate(angle_offset, expand=True)
            found_eyes = _find_eyes_on_image(rotated_pil)
            if found_eyes:
                # Tính góc nghiêng của mắt trên ảnh đã xoay
                dy = found_eyes[1][1] - found_eyes[0][1]
                dx = found_eyes[1][0] - found_eyes[0][0]
                if dx == 0: continue
                angle_on_rotated = float(np.degrees(np.arctan2(dy, dx)))
                final_angle = angle_offset + angle_on_rotated
                angle_components = {"eyes": final_angle}
                detector = "haar_rotated_search"
                break
    elif detector == "haar" and eye_coords is not None:
        dy = eye_coords[1][1] - eye_coords[0][1]
        dx = eye_coords[1][0] - eye_coords[0][0]
        if dx != 0:
            final_angle = float(np.degrees(np.arctan2(dy, dx)))
            angle_components = {"eyes": final_angle}

    absolute_angle = abs(final_angle)
    should_align = (
        absolute_angle >= FACE_ROLL_MIN_DEGREES
        and (force_align or absolute_angle >= FACE_ROLL_AUTO_ALIGN_DEGREES)
    )

    if detector == "none":
        reason = "landmarks_unavailable"
    elif absolute_angle < FACE_ROLL_MIN_DEGREES:
        reason = "already_aligned"
    elif force_align:
        reason = "client_forced"
    elif absolute_angle >= FACE_ROLL_AUTO_ALIGN_DEGREES:
        reason = "above_auto_align_threshold"
    elif absolute_angle >= FACE_ROLL_WARN_DEGREES:
        reason = "warning_only"
    else:
        reason = "within_tolerance"

    metadata = {
        "applied": should_align,
        "face_roll_degrees": round(final_angle, 2),
        "absolute_face_roll_degrees": round(absolute_angle, 2),
        "detector": detector,
        "reason": reason,
        "components": {
            name: round(angle, 2) for name, angle in angle_components.items()
        },
        "warning_threshold_degrees": FACE_ROLL_WARN_DEGREES,
        "auto_align_threshold_degrees": FACE_ROLL_AUTO_ALIGN_DEGREES,
    }

    if not should_align:
        return img_pil, metadata

    # Lấy màu nền để fill các góc trống thay vì màu đen
    bg_color_name = detect_source_bg_color(img_pil)
    fill_color = (255, 255, 255) # Mặc định trắng cho RGB
    if bg_color_name == "blue":
        fill_color = (78, 162, 229) # Xanh dương chuẩn
    elif bg_color_name == "red":
        fill_color = (255, 0, 0)

    # Chuyển về RGB để rotate với fillcolor 3-tuple (tránh lỗi kênh alpha)
    img_rgb = img_pil.convert("RGB")
    rotated_rgb = img_rgb.rotate(final_angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=fill_color)
    
    return rotated_rgb, metadata


def detect_face(img_pil: Image.Image) -> tuple[int, int, int, int] | None:
    """
    Phát hiện khuôn mặt lớn nhất bằng InsightFace (nếu có) hoặc Haar Cascade (fallback).
    Trả về: (x, y, w, h)
    """
    # 1. Thử dùng InsightFace (Chính xác cao)
    analyzer = get_face_analyzer()
    if analyzer:
        try:
            cv_img = cv2.cvtColor(np.array(img_pil.convert("RGB")), cv2.COLOR_RGB2BGR)
            faces = analyzer.get(cv_img)
            if faces:
                # Lấy mặt to nhất
                face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
                bbox = face.bbox.astype(int)
                x, y, x2, y2 = bbox
                return (x, y, x2 - x, y2 - y)
        except Exception as e:
            from src.utils.logger import Log
            Log.warning(f"[PHOTO MODEL] InsightFace inference failed, using Haar fallback: {e}")

    # 2. Fallback sang Haar Cascade (Tốc độ cao, độ chính xác thấp hơn)
    cv_img = cv2.cvtColor(np.array(img_pil.convert("RGB")), cv2.COLOR_RGB2BGR)
    gray = cv2.cvtColor(cv_img, cv2.COLOR_BGR2GRAY)

    def _try_detect(image):
        faces = _CASCADE.detectMultiScale(image, scaleFactor=1.1, minNeighbors=5, minSize=(80, 80))
        if len(faces) > 0:
            return max(faces, key=lambda f: f[2] * f[3])
        return None

    face = _try_detect(gray)
    if face is not None:
        return tuple(face.tolist()) # type: ignore

    # Thử xoay nhẹ
    rows, cols = gray.shape
    return None


def get_face_landmarks(img_pil: Image.Image) -> dict | None:
    """
    Lấy các điểm mốc khuôn mặt (landmarks) bằng InsightFace.
    """
    analyzer = get_face_analyzer()
    if not analyzer:
        return None
        
    try:
        cv_img = cv2.cvtColor(np.array(img_pil.convert("RGB")), cv2.COLOR_RGB2BGR)
        faces = analyzer.get(cv_img)
        if not faces:
            return None
            
        face = max(faces, key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]))
        kps = face.kps # 5 points: left_eye, right_eye, nose, left_mouth, right_mouth
        
        return {
            "left_eye": kps[0],
            "right_eye": kps[1],
            "nose": kps[2],
            "left_mouth": kps[3],
            "right_mouth": kps[4],
            "center_nose": kps[2]
        }
    except:
        return None


def calculate_face_crop_box(
    image_size: tuple[int, int],
    face_bbox: tuple[int, int, int, int],
    aspect_ratio: str,
    center_x: float | None = None,
) -> tuple[int, int, int, int]:
    """Tạo crop box nằm trong ảnh và luôn giữ đúng tỷ lệ yêu cầu."""
    ratio_map = {"1:1": 1.0, "3:4": 3 / 4, "4:6": 2 / 3, "2:3": 2 / 3}
    if aspect_ratio not in ratio_map:
        raise ValueError("aspect_ratio chỉ chấp nhận 1:1, 3:4, 4:6 hoặc 2:3.")

    img_w, img_h = image_size
    fx, fy, fw, fh = face_bbox
    ratio = ratio_map[aspect_ratio]
    cx = float(center_x if center_x is not None else fx + fw / 2)

    # Đủ rộng cho vai và đủ cao cho đầu/ngực, sau đó ép theo target ratio.
    crop_w = max(fw * 2.5, fh * 2.8 * ratio)
    if aspect_ratio == "3:4":
        crop_w = max(img_w * 0.2, min(img_w * 0.95, crop_w))
    max_w = min(float(img_w), float(img_h) * ratio)
    crop_w = min(crop_w, max_w)

    final_w = max(1, int(crop_w))
    final_h = max(1, int(round(final_w / ratio)))
    if final_h > img_h:
        final_h = img_h
        final_w = max(1, int(round(final_h * ratio)))

    # Chừa khoảng trống ~30% chiều cao mặt phía trên bbox.
    final_x = int(round(cx - final_w / 2))
    final_y = int(round(fy - fh * 0.30))
    final_x = max(0, min(final_x, img_w - final_w))
    final_y = max(0, min(final_y, img_h - final_h))
    return final_x, final_y, final_w, final_h


# ─── Quality Validation ───────────────────────────────────────────────────────

def validate_photo_quality(img_pil: Image.Image, face_bbox) -> list[str]:
    """
    Kiểm tra các yếu tố chất lượng ảnh quan trọng để đảm bảo ảnh thẻ tốt nhất.
    """
    quality_warnings: list[str] = []
    w, h = img_pil.size
    gray_single = np.array(img_pil.convert("L"))
    gray = cv2.cvtColor(gray_single, cv2.COLOR_GRAY2BGR)

    sharpness = float(cv2.Laplacian(gray_single, cv2.CV_64F).var())
    if sharpness < 60.0:
        quality_warnings.append(
            "Ảnh có dấu hiệu bị mờ. Vui lòng dùng ảnh rõ nét hơn để tăng độ chính xác."
        )

    mean_luma = float(gray_single.mean())
    if mean_luma < 45:
        quality_warnings.append("Ảnh quá tối. Vui lòng tăng ánh sáng khi chụp.")
    elif mean_luma > 225:
        quality_warnings.append("Ảnh quá sáng hoặc bị cháy sáng. Vui lòng giảm ánh sáng khi chụp.")

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
    [TYPE=CROP] Crop chuẩn ảnh thẻ trực tiếp từ ảnh RGB gốc.
    Ưu tiên: 
    1. Giữ tỉ lệ target_w/target_h.
    2. Cân đối mặt (chiếm ~40-45% chiều cao).
    3. Không bao giờ thêm padding (luôn nằm trong ảnh gốc).
    4. Ưu tiên lấy sát đáy (vì đây là ảnh chụp lại từ ảnh thẻ vật lý).
    """
    if face_bbox is None:
        return None

    img_w, img_h = img_rgb.size
    fx, fy, fw, fh = face_bbox
    ratio = target_w / target_h

    # 0. Xác định biên giới hạn (Effective Bounds)
    # Nếu phát hiện nền xanh/trắng, ta sẽ crop trong vùng đó thay vì toàn bộ ảnh
    bg_color = detect_source_bg_color(img_rgb, face_bbox)
    bg_res = get_background_region_bbox(img_rgb, bg_color)
    
    if isinstance(bg_res, Image.Image):
        # Nếu bg_res là Image, nghĩa là đã được perspective transform (làm phẳng)
        # Ta cập nhật lại img_rgb và tính toán lại các thông số
        img_rgb = bg_res
        img_w, img_h = img_rgb.size
        # Sau khi làm phẳng, ta cần detect lại mặt trên ảnh mới
        new_bbox = detect_face(img_rgb)
        if new_bbox is None: return None
        fx, fy, fw, fh = new_bbox
        min_x, min_y, max_x, max_y = 0, 0, img_w, img_h
        eff_w, eff_h = img_w, img_h
    elif bg_res:
        # Nếu là tuple (bounding box thông thường)
        min_x, min_y, max_x, max_y = bg_res
        eff_w = max_x - min_x
        eff_h = max_y - min_y
    else:
        min_x, min_y, max_x, max_y = 0, 0, img_w, img_h
        eff_w, eff_h = img_w, img_h

    # 1. Nếu tỉ lệ hiện tại đã gần khớp (sai số < 3%), chỉ resize vùng đó
    current_ratio = eff_w / eff_h
    if abs(current_ratio - ratio) / ratio < 0.03:
        return img_rgb.crop((min_x, min_y, max_x, max_y)).resize((target_w, target_h), Image.Resampling.LANCZOS)

    # 2. Tính toán kích thước crop lớn nhất trong biên hiệu dụng
    if current_ratio > ratio:
        # Vùng nền quá rộng -> Lấy full chiều cao nền, cắt bớt 2 bên
        crop_h = eff_h
        crop_w = int(crop_h * ratio)
    else:
        # Vùng nền quá hẹp -> Lấy full chiều rộng nền, cắt bớt trên/dưới
        crop_w = eff_w
        crop_h = int(crop_w / ratio)

    # 3. Định tâm theo mặt
    cx = fx + fw // 2
    x1 = cx - crop_w // 2
    x2 = x1 + crop_w

    # Clamp X trong biên hiệu dụng
    if x1 < min_x:
        x1, x2 = min_x, min_x + crop_w
    elif x2 > max_x:
        x2, x1 = max_x, max_x - crop_w

    # 4. Định vị Y thông minh trong biên hiệu dụng
    y2 = max_y
    y1 = y2 - crop_h

    # Bảo vệ đỉnh đầu (trong biên hiệu dụng)
    min_y1 = max(min_y, fy - int(fh * 0.25)) 
    if y1 > min_y1:
        y1 = min_y1
        y2 = y1 + crop_h

    # Đảm bảo y2 không vượt quá max_y sau khi điều chỉnh
    if y2 > max_y:
        y2 = max_y
        y1 = y2 - crop_h

    # 5. Cắt và resize
    cropped = img_rgb.crop((x1, y1, x2, y2))
    return cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)


def crop_portrait_rgba(
    no_bg_rgba: Image.Image,
    target_w: int,
    target_h: int,
    face_bbox: tuple[int, int, int, int] | None = None,
) -> Image.Image | None:
    """
    [TYPE=FULL] Crop chuẩn ảnh thẻ từ ảnh RGBA đã tách nền.
    Dùng getbbox() để tìm viền người qua alpha channel.
    Trả về Image RGBA đã resize hoặc None nếu không tìm thấy mặt.
    """
    bbox = face_bbox or detect_face(no_bg_rgba)
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

def detect_source_bg_color(
    img_rgb: Image.Image,
    face_bbox: tuple[int, int, int, int] | None = None,
) -> str:
    """
    Đoán màu nền gốc bằng cách lấy mẫu 4 góc ảnh và vùng quanh mặt.
    """
    arr = np.array(img_rgb)
    h, w = arr.shape[:2]
    
    # 1. Lấy mẫu 4 góc (loại bỏ nếu là màu đen/xám quá đậm)
    s = 30
    corner_samples = [
        arr[:s, :s], arr[:s, w-s:],
        arr[h-s:, :s], arr[h-s:, w-s:]
    ]
    
    valid_samples = []
    for sample in corner_samples:
        m = sample.mean(axis=(0,1))
        # Nếu không phải màu đen (tổng RGB > 30)
        if m.sum() > 30:
            valid_samples.append(sample.reshape(-1, 3))

    # 2. Lấy mẫu vùng quanh mặt (phía trên đầu và 2 bên vai)
    face_bbox = face_bbox or detect_face(img_rgb)
    if face_bbox:
        fx, fy, fw, fh = face_bbox
        # Vùng trên đầu
        if fy > 20:
            valid_samples.append(arr[max(0, fy-40):fy, fx:fx+fw].reshape(-1, 3))
        # Vùng bên trái mặt
        if fx > 20:
            valid_samples.append(arr[fy:fy+fh, max(0, fx-40):fx].reshape(-1, 3))
        # Vùng bên phải mặt
        if fx + fw < w - 20:
            valid_samples.append(arr[fy:fy+fh, fx+fw:min(w, fx+fw+40)].reshape(-1, 3))

    if not valid_samples:
        return "none"

    all_samples = np.concatenate(valid_samples)
    mean = all_samples.mean(axis=0)

    if all(c > 180 for c in mean) and max(mean) - min(mean) < 40:
        return "white"
    
    dominant = int(np.argmax(mean))
    if dominant == 2 and mean[2] > mean[0] * 1.2: # Blue dominant
        return "blue"
    if dominant == 1 and mean[1] > mean[0] * 1.2: # Green
        return "green"
    if dominant == 0 and mean[0] > mean[2] * 1.2: # Red
        return "red"
    
    return "none"


def order_points(pts: np.ndarray) -> np.ndarray:
    """Sắp xếp 4 điểm theo thứ tự: top-left, top-right, bottom-right, bottom-left."""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect

def perspective_transform(img: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Hiệu chỉnh phối cảnh (deskew) dựa trên 4 điểm góc."""
    rect = order_points(pts)
    (tl, tr, br, bl) = rect

    widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
    widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
    maxWidth = max(int(widthA), int(widthB))

    heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
    heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
    maxHeight = max(int(heightA), int(heightB))

    dst = np.array([
        [0, 0],
        [maxWidth - 1, 0],
        [maxWidth - 1, maxHeight - 1],
        [0, maxHeight - 1]], dtype="float32")

    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(img, M, (maxWidth, maxHeight))
    return warped

def get_background_region_bbox(img_rgb: Image.Image, color_name: str) -> tuple[int, int, int, int] | Image.Image | None:
    """
    Phát hiện và hiệu chỉnh vùng (bounding box) của nền màu (xanh hoặc trắng) trong ảnh.
    Nếu phát hiện thấy biến dạng phối cảnh (xiên), thực hiện perspective transform.
    """
    if color_name not in ["blue", "white"]:
        return None

    cv_img = cv2.cvtColor(np.array(img_rgb), cv2.COLOR_RGB2BGR)
    hsv = cv2.cvtColor(cv_img, cv2.COLOR_BGR2HSV)
    
    if color_name == "blue":
        lower = np.array([90, 50, 50])
        upper = np.array([130, 255, 255])
        mask = cv2.inRange(hsv, lower, upper)
    else: # white
        lower = np.array([0, 0, 180])
        upper = np.array([180, 40, 255])
        mask = cv2.inRange(hsv, lower, upper)

    kernel = np.ones((5,5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    largest_cnt = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest_cnt) < (img_rgb.width * img_rgb.height * 0.05): # Tối thiểu 5%
        return None

    # Thử xấp xỉ contour thành đa giác 4 cạnh (quadrilateral)
    peri = cv2.arcLength(largest_cnt, True)
    approx = cv2.approxPolyDP(largest_cnt, 0.02 * peri, True)

    if len(approx) == 4:
        # Nếu là tứ giác (bị xiên/phối cảnh), thực hiện làm phẳng (deskew)
        warped_cv = perspective_transform(cv_img, approx.reshape(4, 2))
        return Image.fromarray(cv2.cvtColor(warped_cv, cv2.COLOR_BGR2RGB))
    
    # Nếu không phải tứ giác rõ ràng, trả về bounding box như cũ
    x, y, w, h = cv2.boundingRect(largest_cnt)
    return (x, y, x + w, y + h)


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
