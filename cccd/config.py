"""
Configuration for CCCD OCR
"""
import os
from dotenv import load_dotenv

# Load .env file from project root
# config.py is in /cccd/, so .env is in ../.env
basedir = os.path.abspath(os.path.dirname(__file__))
root_dir = os.path.dirname(basedir)
load_dotenv(os.path.join(root_dir, '.env'))



# ========== UPLOAD CONFIG ==========
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

# ========== MODEL CONFIG ==========
MODEL_PATH = "protonx-models/protonx-legal-tc" # Old online path
# Model is located in cccd/local-protonx-model/protonx-legal-tc
# MODEL_PATH = os.path.join(root_dir, "local-protonx-model", "protonx-legal-tc")

# ========== OCR CONFIG ==========
OCR_CONFIG = {
    "lang": "vi",
    "use_textline_orientation": False,
    "use_doc_orientation_classify": False,
    "use_doc_unwarping": False,
    
}

# ========== TEXT CLEANING CONFIG ==========
# Từ khóa chung cần loại bỏ
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
    "GIÂY PHÉP LÁIXE",
    "GIÂY PHÉP LÁIXE/DRIVER'S LICENSE",
    "GIAY PHÉP LÁI XE",
    "CNG HA X HI CH NGHA VIT NAM",
    "GIAY PHÉP LÁI XE",
    "Giấy phép",
    "Giấy phép lái xe",
    
    
    
    # Khẩu hiệu
    "độc lập tự do hạnh phúc",
    "doc lap tu do hanh phuc",
    "Đc lp - Tư do - Hanh phúc",
    "Đc lp - T do - Hnh phúc",
    "độc lập",
    "doc lap",
    "tự do",
    "t - do",
    "tu do",
    "hạnh phúc",
    "hanh phuc",
    "Hnh phúc",
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
    

]

# Từ khóa cho mặt sau (ngày tháng)
DATE_KEYWORDS = [
    "ngày", "tháng", "năm", 
    "cấp", "cap",
    "giá trị", "gia tri",
    "hết hạn", "het han",
    "có giá trị đến", "co gia tri den"
]

# Từ khóa cho mặt trước (Họ tên, Quê quán, Địa chỉ)
FRONT_KEYWORDS = [
    # Họ tên
    "họ", "tên", "ho", "ten", "name", "full name",
    # Quê quán
    "quê", "quán", "que", "quan", "hometown", "origin",
    # Địa chỉ / Nơi thường trú
    "địa chỉ", "dia chi", "address",
    "nơi", "noi", "thường trú", "thuong tru", "cư trú", "cu tru",
    "residence", "place"
]

# ========== EXTRACTION CONFIG ==========
# Từ khóa địa chỉ
ADDRESS_KEYWORDS = [
    "nơi cư trú", "cư trú", "nơi thuong tru", "thường trú",
    "thuong tru", "place of residence", "residence"
]

# Từ khóa ngày hết hạn
EXPIRY_LABEL_KEYWORDS = [
    "có giá trị đến", "co gia tri den", "có giá tr đén"
]

# Từ khóa quê quán
HOMETOWN_KEYWORDS = [
    "quê quán", "quê quan", "quê", "que quan", "que",
]

# Giá trị mặc định
DEFAULT_NATIONALITY = "Việt Nam"
DEFAULT_PLACE_OF_ISSUE = "CỤC TRƯỞNG CỤC CẢNH SÁT QUẢN LÝ HÀNH CHÍNH VỀ TRẬT TỰ XÃ HỘI"

# ========== GEMINI CONFIG ==========
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
