from flask import Flask, request, jsonify
from flask_cors import CORS
from paddleocr import PaddleOCR
import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import os
import re
from datetime import datetime
import time

app = Flask(__name__)
CORS(app)

# ========== CONFIG ==========
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
ALLOWED_EXT = {'png', 'jpg', 'jpeg'}

MODEL_PATH = "protonx-models/protonx-legal-tc"

# ========== LOAD MODELS ==========
ocr = PaddleOCR(lang="vi", use_textline_orientation=False, 
use_doc_orientation_classify=False,
use_doc_unwarping=False,
)
device = torch.device("cuda" if torch.cuda.is_available() else "cpu",)
tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_PATH).to(device)
model.eval()

# ===============================================================
#                       UTILS
# ===============================================================

def allowed_file(name):
    return "." in name and name.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def ocr_extract(path):
    """OCR → list of text lines"""
    start_time = time.time()
    print(f"\n{'='*60}")
    print(f"[OCR] 🔍 Bắt đầu OCR: {path}")
    print(f"[OCR] ⏰ Thời gian: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
    
    result = ocr.predict(path)
    
    for block in result:
        elapsed = time.time() - start_time
        num_lines = len(block["rec_texts"])
        print(f"[OCR] ✅ Hoàn thành OCR")
        print(f"[OCR] 📝 Số dòng text: {num_lines}")
        print(f"[OCR] ⏱️  Thời gian: {elapsed:.2f}s")
        
        # 📋 LOG CHI TIẾT: Hiển thị từng dòng text + confidence
        print(f"\n{'─'*60}")
        print(f"[OCR] 📋 CHI TIẾT TEXT DETECT:")
        print(f"{'─'*60}")
        for i, (text, score) in enumerate(zip(block["rec_texts"], block["rec_scores"]), 1):
            confidence = score * 100
            emoji = "✅" if confidence >= 80 else "⚠️" if confidence >= 60 else "❌"
            print(f"[OCR] {emoji} [{i:2d}] [{confidence:5.1f}%] {text[:70]}")
        print(f"{'─'*60}\n")
        
        print(f"{'='*60}\n")
        return block["rec_texts"], block["rec_scores"]
    
    print(f"[OCR] ⚠️  Không tìm thấy text")
    return [], []


def filter_useless_lines(lines):
    """Lọc bỏ các dòng text chung không cần thiết"""
    print(f"\n{'='*60}")
    print(f"[FILTER] 🗑️  Bắt đầu lọc text không cần thiết")
    print(f"[FILTER] 📝 Số dòng ban đầu: {len(lines)}")
    
    # ⚠️ Kiểm tra input rỗng
    if len(lines) == 0:
        print(f"[FILTER] ⚠️  CẢNH BÁO: Không có dòng text nào từ OCR!")
        print(f"{'='*60}\n")
        return []
    
    # Danh sách các từ khóa chung cần loại bỏ (mở rộng)
    USELESS_KEYWORDS = [
        # Tiêu đề quốc gia
        "cộng hòa xã hội chủ nghĩa việt nam",
        "cong hoa xa hoi chu nghia viet nam",
        "cộng hoà",
        "cong hoa",
        "xã hội chủ nghĩa",
        "xa hoi chu nghia",
        "socialist republic",
        "socialist",
        "republic",
        
        # Khẩu hiệu
        "độc lập tự do hạnh phúc",
        "doc lap tu do hanh phuc",
        "độc lập",
        "doc lap",
        "tự do",
        "tu do",
        "hạnh phúc",
        "hanh phuc",
        "independence",
        "freedom",
        "freedor",  # Lỗi OCR thường gặp
        "happiness",
        
        # Loại giấy tờ
        "căn cước công dân",
        "can cuoc cong dan",
        "căn cước",
        "can cuoc",
        "công dân",
        "cn",
        "dn",
        "chứng minh nhân dân",
        "chung minh nhan dan",
        "chứng minh",
        "chung minh",
        "identity card",
        "citizen identity",
        "id card",
        "cccd",
        "cmnd",
        
        # Từ khóa tiếng Việt không dấu (OCR thường nhầm)
        "cng ha",
        "nghia vit nam",
        "vit nam",
        "viet nam",
    ]
    
    filtered = []
    removed_count = 0
    
    for line in lines:
        line_lower = line.lower().strip()
        
        # Bỏ qua dòng rỗng
        if not line_lower:
            continue
        
        # Kiểm tra xem có chứa từ khóa không cần thiết không
        is_useless = False
        matched_keyword = ""
        
        for keyword in USELESS_KEYWORDS:
            if keyword in line_lower:
                is_useless = True
                matched_keyword = keyword
                removed_count += 1
                break
        
        if is_useless:
            print(f"[FILTER] ❌ Loại bỏ (từ khóa '{matched_keyword}'): '{line[:60]}'")
        else:
            filtered.append(line)
            print(f"[FILTER] ✅ Giữ lại: '{line[:60]}'")
    
    print(f"\n[FILTER] 📊 Kết quả:")
    print(f"[FILTER]    Đã loại bỏ: {removed_count} dòng")
    print(f"[FILTER]    Còn lại: {len(filtered)} dòng")
    print(f"{'='*60}\n")
    
    return filtered



def clean_text(lines):
    """Clean OCR bằng transformer từng dòng"""
    start_time = time.time()
    print(f"\n{'='*60}")
    print(f"[CLEAN] 🧹 Bắt đầu làm sạch text")
    print(f"[CLEAN] ⏰ Thời gian: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
    print(f"[CLEAN] 📝 Số dòng cần xử lý: {len(lines)}")
    print(f"{'='*60}")
    
    cleaned = []
    for idx, line in enumerate(lines, 1):
        line_start = time.time()
        print(f"\n[CLEAN] 🔄 Dòng {idx}/{len(lines)}: {line[:50]}...")
        
        inputs = tokenizer(
            line, 
            return_tensors="pt",
            truncation=True, 
            max_length=80  # ⚡ Giảm từ 160 → 80
        ).to(device)

        gen_start = time.time()
        outputs = model.generate(
            **inputs,
            max_new_tokens=80,        # ⚡ Giảm từ 160 → 80
            num_beams=3,              # ⚡ GIẢM TỪ 10 → 3 (tăng tốc 3x)
            num_return_sequences=1,
            early_stopping=True,
            do_sample=False,          # ⚡ Tắt sampling để nhanh hơn
            length_penalty=1.0        # ⚡ Không phạt độ dài
        )
        gen_elapsed = time.time() - gen_start

        cleaned_line = tokenizer.decode(outputs[0], skip_special_tokens=True)
        cleaned.append(cleaned_line)
        
        line_elapsed = time.time() - line_start
        print(f"[CLEAN] ✅ Kết quả: {cleaned_line[:50]}...")
        print(f"[CLEAN] ⏱️  Thời gian generate: {gen_elapsed:.2f}s")
        print(f"[CLEAN] ⏱️  Tổng thời gian dòng: {line_elapsed:.2f}s")

    total_elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"[CLEAN] ✅ Hoàn thành làm sạch {len(lines)} dòng")
    print(f"[CLEAN] ⏱️  Tổng thời gian: {total_elapsed:.2f}s")
    print(f"[CLEAN] 📊 Trung bình: {total_elapsed/len(lines):.2f}s/dòng")
    print(f"{'='*60}\n")
    
    return cleaned


def selective_clean_text_back(lines):
    """
    CHỈ clean text cho các dòng chứa ngày tháng (mặt sau)
    Các dòng khác giữ nguyên để tiết kiệm thời gian
    """
    start_time = time.time()
    print(f"\n{'='*60}")
    print(f"[CLEAN-SELECTIVE] 🎯 Làm sạch có chọn lọc (chỉ ngày tháng)")
    print(f"[CLEAN-SELECTIVE] ⏰ Thời gian: {datetime.now().strftime('%H:%M:%S.%f')[:-3]}")
    print(f"[CLEAN-SELECTIVE] 📝 Số dòng ban đầu: {len(lines)}")
    print(f"{'='*60}")
    
    # ⚠️ Kiểm tra input rỗng
    if len(lines) == 0:
        print(f"[CLEAN-SELECTIVE] ⚠️  CẢNH BÁO: Không có dòng text nào!")
        print(f"{'='*60}\n")
        return []
    
    # Từ khóa để nhận diện dòng cần clean
    DATE_KEYWORDS = [
        "ngày", "tháng", "năm", 
        "cấp", "cap",
        "giá trị", "gia tri",
        "hết hạn", "het han",
        "có giá trị đến", "co gia tri den"
    ]
    
    cleaned = []
    cleaned_count = 0
    skipped_count = 0
    
    for idx, line in enumerate(lines, 1):
        line_lower = line.lower()
        
        # Kiểm tra xem dòng này có chứa thông tin ngày tháng không
        needs_cleaning = any(keyword in line_lower for keyword in DATE_KEYWORDS)
        
        if needs_cleaning:
            # Clean dòng này
            print(f"\n[CLEAN-SELECTIVE] 🧹 Dòng {idx}/{len(lines)} - CẦN CLEAN")
            print(f"[CLEAN-SELECTIVE]    📥 TRƯỚC: '{line[:60]}'")
            line_start = time.time()
            
            inputs = tokenizer(
                line, 
                return_tensors="pt",
                truncation=True, 
                max_length=80
            ).to(device)

            outputs = model.generate(
                **inputs,
                max_new_tokens=80,
                num_beams=3,
                num_return_sequences=1,
                early_stopping=True,
                do_sample=False,
                length_penalty=1.0
            )

            cleaned_line = tokenizer.decode(outputs[0], skip_special_tokens=True)
            cleaned.append(cleaned_line)
            cleaned_count += 1
            
            line_elapsed = time.time() - line_start
            print(f"[CLEAN-SELECTIVE]    📤 SAU:   '{cleaned_line[:60]}'")
            print(f"[CLEAN-SELECTIVE]    ⏱️  Thời gian: {line_elapsed:.2f}s")
        else:
            # Giữ nguyên dòng này
            print(f"[CLEAN-SELECTIVE] ⏭️  Dòng {idx}/{len(lines)} - BỎ QUA: '{line[:60]}'")
            cleaned.append(line)
            skipped_count += 1
    
    total_elapsed = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"[CLEAN-SELECTIVE] ✅ Hoàn thành")
    print(f"[CLEAN-SELECTIVE] 📊 Đã clean: {cleaned_count} dòng")
    print(f"[CLEAN-SELECTIVE] ⏭️  Đã bỏ qua: {skipped_count} dòng")
    print(f"[CLEAN-SELECTIVE] ⏱️  Tổng thời gian: {total_elapsed:.2f}s")
    
    # ⚠️ Tránh chia cho 0
    if len(lines) > 0:
        print(f"[CLEAN-SELECTIVE] 💡 Tiết kiệm: {skipped_count / len(lines) * 100:.1f}%")
    else:
        print(f"[CLEAN-SELECTIVE] ⚠️  Không có dòng nào để xử lý")
    
    print(f"{'='*60}\n")
    
    return cleaned


# ===============================================================
#                       EXTRACTION RULES
# ===============================================================

def clean_label(text):
    return re.sub(r"[:\-\.]*$", "", text.strip().lower())


import re

def extract_front(texts):
    info = {
        "idNumber": "",
        "fullName": "",
        "dob": "",
        "gender": "",
        "nationality": "Việt Nam",
        "hometown": "",
        "address": "",
        "expiryDate": "",
    }

    # Join full text
    full = " ".join(texts).lower()

    # ==========================
    # 1. CCCD: 9 hoặc 12 số
    # ==========================
    m = re.search(r"\b(\d{9}|\d{12})\b", full)
    if m:
        info["idNumber"] = m.group()

    # ==========================
    # 2. HỌ TÊN: Xử lý 3 trường hợp
    # ==========================
    # Regex để validate tên (ALL CAPS, có chữ cái tiếng Việt)
    name_regex = re.compile(r"^(?=.*[A-ZÀ-ỸĐ])[A-ZÀ-ỸĐ\s]{3,}$")
    
    # CHIẾN LƯỢC 1: Tìm label "Họ và tên" → lấy dòng TIẾP THEO
    for i, t in enumerate(texts):
        t_lower = t.lower().strip()
        # Kiểm tra xem có phải dòng label không
        if t_lower in ["họ và tên", "ho va ten", "họ tên", "ho ten", "full name", "name"]:
            # Lấy dòng tiếp theo (nếu có)
            if i + 1 < len(texts):
                next_line = texts[i + 1].strip()
                # Validate: Phải là ALL CAPS và có ít nhất 3 ký tự
                if name_regex.match(next_line):
                    info["fullName"] = next_line
                    print(f"[EXTRACT] ✅ Họ tên (label + next line): '{next_line}'")
                    break
    
    # CHIẾN LƯỢC 2: Tìm dòng chứa "Họ và tên: NGUYỄN VĂN A" (cùng dòng)
    if not info["fullName"]:
        for t in texts:
            if any(k in t.lower() for k in ["họ và tên", "họ tên", "ho ten", "ho va ten"]):
                # Xóa label, lấy phần còn lại
                cleaned = re.sub(r"(họ và tên|họ tên|ho va ten|ho ten)[:\-\s]*", "", t, flags=re.I)
                cleaned = cleaned.strip()
                # Validate: Phải là ALL CAPS
                if cleaned and name_regex.match(cleaned):
                    info["fullName"] = cleaned
                    print(f"[EXTRACT] ✅ Họ tên (same line): '{cleaned}'")
                    break
    
    # CHIẾN LƯỢC 3: Tìm dòng ALL CAPS (fallback - ưu tiên dòng dài)
    if not info["fullName"]:
        candidates = []
        for t in texts:
            t_stripped = t.strip()
            if name_regex.match(t_stripped):
                # Loại trừ các dòng không phải tên
                if not any(exclude in t_stripped.upper() for exclude in [
                    "CỘNG HÒA", "SOCIALIST", "VIỆT NAM", "VIET NAM",
                    "CĂN CƯỚC", "CHỨNG MINH", "CCCD", "CMND"
                ]):
                    candidates.append(t_stripped)
        
        # Chọn dòng dài nhất (thường là tên đầy đủ)
        if candidates:
            info["fullName"] = max(candidates, key=len)
            print(f"[EXTRACT] ✅ Họ tên (ALL CAPS fallback): '{info['fullName']}'")

    # ==========================
    # 3. Ngày sinh (DOB)
    # ==========================
    dob_regex = re.compile(
        r"(?i)(?:ngày\s*sinh|date\s*of\s*birth|birth)[:\s]*"
        r"(\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4})"
    )

    # Regex chỉ bắt ngày (dùng cho dòng phía dưới)
    date_only_regex = re.compile(r"\b(\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4})\b")

    for i, t in enumerate(texts):
        mm = dob_regex.search(t)
        if mm:
            # Trường hợp ngày nằm chung 1 dòng
            if mm.group(1):
                info["dob"] = mm.group(1)
                break

        # Trường hợp ngày NẰM Ở DÒNG PHÍA DƯỚI
        if i + 1 < len(texts):
            mm2 = date_only_regex.search(texts[i + 1])
            if mm2:
                info["dob"] = mm2.group(1)
                break

# Nếu vẫn chưa có dob -> fallback (tự động quét toàn bộ)
    if not info["dob"]:
        for t in texts:
            mm = date_only_regex.search(t)
            if mm:
                info["dob"] = mm.group(1)
                break

    # ==========================
    # 4. Giới tính
    # ==========================
    if "nam" in full :
        info["gender"] = "Nam"
    else:
        info["gender"] = "Nữ"

    # ==========================
    # 5. Quê quán (hometown)
    # ==========================
    hometown_keywords = [
        "quê quán", "quê quan", "quê", "que quan", "que", 
        
    ]

    # Strategy 1: Label on one line → value next line
    for i, t in enumerate(texts):
        t_clean = clean_label(t)
        if any(k in t_clean for k in hometown_keywords):
            if i + 1 < len(texts):
                candidate = texts[i + 1].strip()
                if len(candidate) > 3:  # minimal content validation
                    info["hometown"] = candidate
                    print(f"[EXTRACT] ✅ Hometown (next line): {candidate}")
                    break

    # Strategy 2: Same line (e.g. 'Quê quán: Nam Định')
    if not info["hometown"]:
        for t in texts:
            t_lower = clean_label(t)
            for k in hometown_keywords:
                if k in t_lower:
                    # Remove label part
                    cleaned = re.sub(rf"{k}\s*[:\-]*\s*", "", t, flags=re.I).strip()
                    if len(cleaned) > 3:
                        info["hometown"] = cleaned
                        print(f"[EXTRACT] ✅ Hometown (same line): {cleaned}")
                        break
            if info["hometown"]:
                break

    # Strategy 3: Fallback – tìm dòng bắt đầu bằng 'Quê ...' nhưng OCR lỗi dấu
    if not info["hometown"]:
        for t in texts:
            t_l = t.lower()
            if t_l.startswith("que ") or t_l.startswith("quequan") or "que quan" in t_l:
                info["hometown"] = t.split(":")[-1].strip()
                print(f"[EXTRACT] 🟡 Hometown (fallback guess): {info['hometown']}")
                break

    # ==========================
    # 6. ĐỊA CHỈ 2 DÒNG (CHUẨN)
    # ==========================
    address_keywords = [
        "nơi cư trú", "cư trú", "nơi thuong tru", "thường trú", 
        "thuong tru", "place of residence", "residence"
    ]

    expiry_keywords = [
        "có giá trị đến", "co gia tri den",
        "date of expiry", "expiry"
    ]

    for i, t in enumerate(texts):
        t_lower = t.lower()

        # Nếu là label địa chỉ
        if any(k in t_lower for k in address_keywords):

            # --- Strategy 1: same line ---
            cleaned = re.sub(
                r"(nơi cư trú|cư trú|nơi thường trú|thường trú|place of residence)[:\-\s]*",
                "",
                t,
                flags=re.I
            ).strip()

            address = ""

            # Nếu same line có sẵn địa chỉ → lấy luôn
            if len(cleaned) > 5:
                address = cleaned

            # --- Strategy 2: địa chỉ nằm ở dòng tiếp theo ---
            if not address and i + 1 < len(texts):
                next_line = texts[i + 1].strip()

                # Nếu next line KHÔNG PHẢI expiry → đây là địa chỉ dòng 2
                if not any(exp in next_line.lower() for exp in expiry_keywords):
                    address = next_line

                    # Check thêm dòng thứ 3 nếu vẫn không phải expiry
                    if i + 2 < len(texts):
                        third_line = texts[i + 2].strip()
                        if not any(exp in third_line.lower() for exp in expiry_keywords):
                            # nhưng phải đảm bảo đúng địa chỉ, không phải text linh tinh
                            if len(third_line) > 5:
                                address += ", " + third_line

            info["address"] = address
            print(f"[EXTRACT] ✅ Address detected: {address}")
            break

        # ==========================
    # 7. Expiry date: "có giá trị đến"
    # ==========================
    expiry_regex = re.compile(
        r"(?i)có\s+giá\s+trị\s+đến[:\s]*"
        r"(\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4})"
    )

    for t in texts:
        m = expiry_regex.search(t)
        if m:
            info["expiryDate"] = m.group(1)
            break

    return info



def extract_back(texts):
    info = {
        "dateOfIssue": "",
        "placeOfIssue": "CỤC TRƯỞNG CỤC CẢNH SÁT QUẢN LÝ HÀNH CHÍNH VỀ TRẬT TỰ XÃ HỘI"
    }

    full = " ".join(texts).lower()

    # ==========================
    # 1. Ngày cấp: "ngày, tháng, năm"
    # ==========================
    issue_regex = re.compile(
        r"(?i)ngày\s*[,\.]?\s*tháng\s*[,\.]?\s*năm.*?"
        r"(\d{1,2}[\/\-.]\d{1,2}[\/\-.]\d{2,4})"
    )

    for t in texts:
        m = issue_regex.search(t)
        if m:
            info["dateOfIssue"] = m.group(1)
            break



    return info



# ===============================================================
#                       MAIN API
# ===============================================================

@app.route("/api/detect", methods=["POST"])
def detect():
    request_start = time.time()
    print(f"\n\n{'#'*70}")
    print(f"{'#'*70}")
    print(f"###  🚀 BẮT ĐẦU REQUEST MỚI")
    print(f"###  ⏰ Thời gian: {datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]}")
    print(f"{'#'*70}")
    print(f"{'#'*70}\n")
    
    try:
        # Validate
        step_start = time.time()
        print(f"[API] 📋 Bước 1: Validate request...")
        
        if "front_image" not in request.files or "back_image" not in request.files:
            print(f"[API] ❌ Thiếu file ảnh")
            return jsonify({"statusCode": 400, "message": "Thiếu file"}), 400

        f1 = request.files["front_image"]
        f2 = request.files["back_image"]

        if not allowed_file(f1.filename) or not allowed_file(f2.filename):
            print(f"[API] ❌ Sai định dạng file")
            return jsonify({"statusCode": 400, "message": "Sai định dạng file"}), 400

        print(f"[API] ✅ Validation OK - {time.time() - step_start:.2f}s\n")

        # Save
        step_start = time.time()
        print(f"[API] 💾 Bước 2: Lưu file...")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        p1 = os.path.join(UPLOAD_FOLDER, f"{ts}_front.jpg")
        p2 = os.path.join(UPLOAD_FOLDER, f"{ts}_back.jpg")
        f1.save(p1)
        f2.save(p2)
        print(f"[API] ✅ Đã lưu file - {time.time() - step_start:.2f}s")
        print(f"[API]    📁 Front: {p1}")
        print(f"[API]    📁 Back: {p2}\n")

        # OCR Front
        step_start = time.time()
        print(f"[API] 🔍 Bước 3: OCR mặt trước...")
        raw_front, _ = ocr_extract(p1)
        ocr_front_time = time.time() - step_start
        print(f"[API] ✅ OCR mặt trước xong - {ocr_front_time:.2f}s\n")

        # OCR Back
        step_start = time.time()
        print(f"[API] 🔍 Bước 4: OCR mặt sau...")
        raw_back, _ = ocr_extract(p2)
        ocr_back_time = time.time() - step_start
        print(f"[API] ✅ OCR mặt sau xong - {ocr_back_time:.2f}s\n")

        # Filter Front
        step_start = time.time()
        print(f"[API] 🗑️  Bước 5: Lọc text mặt trước...")
        filtered_front = filter_useless_lines(raw_front)
        filter_front_time = time.time() - step_start
        print(f"[API] ✅ Lọc mặt trước xong - {filter_front_time:.2f}s\n")

        # Filter Back
        step_start = time.time()
        print(f"[API] 🗑️  Bước 6: Lọc text mặt sau...")
        filtered_back = filter_useless_lines(raw_back)
        filter_back_time = time.time() - step_start
        print(f"[API] ✅ Lọc mặt sau xong - {filter_back_time:.2f}s\n")

        # 🧹 Clean mặt trước (toàn bộ)
        step_start = time.time()
        print(f"[API] 🧹 Bước 7: Làm sạch mặt trước (toàn bộ)...")
        clean_front = clean_text(filtered_front)
        clean_front_time = time.time() - step_start
        print(f"[API] ✅ Làm sạch mặt trước xong - {clean_front_time:.2f}s\n")

        # ⚡ Clean có chọn lọc mặt sau (chỉ ngày tháng)
        step_start = time.time()
        print(f"[API] 🎯 Bước 8: Làm sạch có chọn lọc mặt sau (chỉ ngày tháng)...")
        clean_back = selective_clean_text_back(filtered_back)
        clean_back_time = time.time() - step_start
        print(f"[API] ✅ Làm sạch mặt sau xong - {clean_back_time:.2f}s\n")

        # Extract
        step_start = time.time()
        print(f"[API] 📊 Bước 9: Trích xuất thông tin...")
        info_front = extract_front(clean_front)
        info_back = extract_back(clean_back)
        extract_time = time.time() - step_start
        print(f"[API] ✅ Trích xuất xong - {extract_time:.2f}s\n")

        total_time = time.time() - request_start

        # Summary
        print(f"\n{'='*70}")
        print(f"📊 TỔNG KẾT THỜI GIAN")
        print(f"{'='*70}")
        print(f"  OCR mặt trước:        {ocr_front_time:>8.2f}s")
        print(f"  OCR mặt sau:          {ocr_back_time:>8.2f}s")
        print(f"  Lọc mặt trước:        {filter_front_time:>8.2f}s")
        print(f"  Lọc mặt sau:          {filter_back_time:>8.2f}s")
        print(f"  Clean mặt trước:      {clean_front_time:>8.2f}s  🧹 (TOÀN BỘ)")
        print(f"  Clean mặt sau:        {clean_back_time:>8.2f}s  🎯 (CHỈ NGÀY)")
        print(f"  Trích xuất:           {extract_time:>8.2f}s")
        print(f"  {'─'*70}")
        print(f"  TỔNG CỘNG:            {total_time:>8.2f}s")
        print(f"{'='*70}\n")

        print(f"[API] 🎉 Trả về kết quả cho client\n")

        return jsonify({
            "statusCode": 200,
            "message": "Success",
            "data": {**info_front, **info_back},
            "debug": {
                "total_time": f"{total_time:.2f}s",
                "ocr_time": f"{ocr_front_time + ocr_back_time:.2f}s",
                "filter_time": f"{filter_front_time + filter_back_time:.2f}s",
                "clean_time": f"{clean_front_time + clean_back_time:.2f}s"
            }
        })

    except Exception as e:
        error_time = time.time() - request_start
        print(f"\n{'!'*70}")
        print(f"[API] ❌ LỖI XẢY RA")
        print(f"[API] ⏱️  Thời gian trước khi lỗi: {error_time:.2f}s")
        print(f"[API] 💥 Chi tiết lỗi: {str(e)}")
        print(f"{'!'*70}\n")
        
        return jsonify({
            "statusCode": 500,
            "message": "Lỗi server",
            "error": str(e)
        }), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
