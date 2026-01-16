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

# Fix Paddle OCR hanging issue (oneDNN)
os.environ["ONEDNN_PRIMITIVE_CACHE_CAPACITY"] = "10"



# ========== UPLOAD CONFIG ==========
UPLOAD_FOLDER = "uploads"
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'md', 'docx', 'doc'}
MAX_RAG_FILE_SIZE = 5 * 1024 * 1024  # 5 MB per file for RAG
MAX_OCR_FILE_SIZE = 10 * 1024 * 1024  # 10 MB limit for general OCR
MAX_FILE_COUNT = 5 # Maximum files per upload
MAX_DOCUMENTS_PER_WORKSPACE = 10 # Maximum documents per workspace
 
 # ========== DOCUMENT STATUS ==========
class DocStatus:
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"

# ========== MODEL CONFIG ==========
YOLO_MODEL_PATH = "yolo_model/yolo_v8n_model.pt"  # Đường dẫn tới file .pt của bạn
YOLO_LABEL_MAP = {
    "id": "idNumber",
    "name": "fullName",
    "dob": "dob",
    "gender": "gender",
    "nationality": "nationality",
    "origin_place": "hometown",
    "current_place": "address",
    "expire_date": "expiryDate"
}
MODEL_PATH = "protonx-models/nano-protonx-legal-tc" # Old online path
# Model is located in cccd/local-protonx-model/protonx-legal-tc
# MODEL_PATH = os.path.join(root_dir, "local-protonx-model", "protonx-legal-tc")

# ========== OCR CONFIG ==========
OCR_CONFIG = {
    "lang": "vi",
    "use_angle_cls": True, # Enable Angle Classification
    "use_doc_orientation_classify": True, # Native orientation detection
    "use_doc_unwarping": False,
    "enable_mkldnn": True, # Acceleration for Intel CPUs
    "cpu_threads": 3, # Parallel processing
    "det_limit_side_len": 960, # Reduced from 1280 for faster detection
    "det_db_unclip_ratio": 1.8, # Balanced for speed/accuracy
}

# ========== TEXT CLEANING CONFIG ==========
# LƯU Ý: Với CCCD Mặt trước, các flow USELESS_KEYWORDS và FRONT_KEYWORDS sẽ bị bỏ qua 
# để sử dụng Layout Detection (YOLOv8) thay thế.
# Từ khóa chung cần loại bỏ
USELESS_KEYWORDS = [
    # Tiêu đề quốc gia
    "cộng hòa xã hội chủ nghĩa",
    "cong hoa xa hoi chu nghia",
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
    "CNG HA X HI CH NGHA",
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
    
    # Vehicle Document specific noise
    "thông số kỹ thuật", "specifications", "ct bánh xe", "vết bánh xe", "tire size",
    "kích thước", "khối lượng", "weight", "kerb mass", "payload", "tổng tải",
    "số người", "chỗ đứng", "chỗ nằm", "seating", "standing", "lying",
    "dung tích", "engine displacement", "công suất", "loại nhiên liệu", "fuel",
    "áp suất", "lốp xe", "number of tires", "vận tốc",
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

# Từ khóa cho mặt sau (Họ tên, Quê quán, Địa chỉ)
BACK_KEYWORDS = [
    "Ngày, tháng, năm", "Date, month, year.",
    "QUẢN LÝ HÀNH CHÍNH", "cục trưởng", "cục hành chính"

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

# ========== GENERIC REGEX ==========
COMMON_COUNTRIES_REGEX = r"Việt Nam|Trung Quốc|Lào|Campuchia|Thái Lan|Myanmar|Malaysia|Singapore|Indonesia|Philippines|Brunei|Đông Timor|Hàn Quốc|Triều Tiên|Nhật Bản|Mông Cổ|Đài Loan|Ấn Độ|Nga|Mỹ|Hoa Kỳ|Anh|Pháp|Đức|Ý|Tây Ban Nha|Bồ Đào Nha|Úc|Canada|Brasil|Argentina|Nam Phi|Ai Cập"

# Giá trị mặc định
DEFAULT_NATIONALITY = "Việt Nam"
DEFAULT_PLACE_OF_ISSUE = "CỤC TRƯỞNG CỤC CẢNH SÁT QUẢN LÝ HÀNH CHÍNH VỀ TRẬT TỰ XÃ HỘI"

# ========== AI API KEY CONFIG ==========
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
OPENROUTER_GROK_API_KEY = os.getenv("OPENROUTER_GROK_API_KEY", "")

# ========== MONGODB CONFIG ==========
MONGODB_URI = os.getenv("MONGODB_URI", "")

# ========== JWT CONFIG ==========
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "super-secret-key-change-me")
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 15
REFRESH_TOKEN_EXPIRE_DAYS = 7
# ========== CLOUDINARY CONFIG ==========
CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "")
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "")
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "")

# ========== QDRANT CONFIG ==========
QDRANT_URL = os.getenv("QDRANT_URL", "")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")

# ========== RAG CONFIG ==========
RAG_COLLECTION_NAME = "documents_rag"
RAG_CHUNK_SIZE = 800
RAG_CHUNK_OVERLAP = 100
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5" # FastEmbed will use this or default


AUTH_API_URL = os.getenv("AUTH_SERVICE_URL", "")