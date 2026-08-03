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

# ========== DeepDoc + VietOCR paths (override via .env) ==========
# DEEPDOC_ONNX_DIR  = path to directory containing det.onnx
# VIETOCR_WEIGHT    = path to vgg_seq2seq.pth weight file



# ========== UPLOAD CONFIG ==========
UPLOAD_FOLDER = "uploads"
BASE_URL = os.getenv("BASE_URL", "http://192.168.1.241:9000")
CHATBOT_EMBED_CDN_URL = os.getenv("CHATBOT_EMBED_CDN_URL", None)
N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL", "https://tlhuy02.app.n8n.cloud/webhook-test/chat-runtime")
TTS_FILE_RETENTION_HOURS = int(os.getenv("TTS_FILE_RETENTION_HOURS", "24"))
PHOTO_TEMP_RETENTION_DAYS = max(1, min(365, int(os.getenv("PHOTO_TEMP_RETENTION_DAYS", "30"))))
PHOTO_SIGNED_URL_EXPIRY_SECONDS = max(
    300,
    min(24 * 3600, int(os.getenv("PHOTO_SIGNED_URL_EXPIRY_SECONDS", "3600"))),
)
PHOTO_BATCH_TIMEOUT_SECONDS = max(
    20,
    min(600, int(os.getenv("PHOTO_BATCH_TIMEOUT_SECONDS", "120"))),
)
PHOTO_FACE_ROLL_WARN_DEGREES = max(
    1.0,
    min(15.0, float(os.getenv("PHOTO_FACE_ROLL_WARN_DEGREES", "5.0"))),
)
PHOTO_FACE_ROLL_AUTO_ALIGN_DEGREES = max(
    PHOTO_FACE_ROLL_WARN_DEGREES,
    min(25.0, float(os.getenv("PHOTO_FACE_ROLL_AUTO_ALIGN_DEGREES", "8.0"))),
)

# Định dạng file tài liệu cho OCR / RAG
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'pdf', 'md', 'docx', 'doc', 'xlsx'}

# Định dạng ảnh dùng cho avatar / ảnh đại diện
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
MAX_RAG_FILE_SIZE = 100 * 1024 * 1024  # 100 MB per file for RAG
MAX_OCR_FILE_SIZE = 10 * 1024 * 1024  # 10 MB limit for general OCR
MAX_FILE_COUNT = 5 # Maximum files per upload
MAX_DOCUMENTS_PER_WORKSPACE = 10 # Maximum documents per workspace
 
# ========== DOCUMENT STATUS ==========
class DocStatus:
    UPLOADED = "UPLOADED"
    PROCESSING = "PROCESSING"
    READY = "READY"
    FAILED = "FAILED"

# ========== CHATBOT COLOR ==========
class ChatbotColor:
    DEFAULT = 0
    BLUE = 1
    GREEN = 2
    PURPLE = 3
    PINK = 4

# ========== MODEL CONFIG ==========
# AI model path (transformers)
MODEL_PATH = "protonx-models/distilled-protonx-legal-tc" # Global instance
# Model is located in cccd/local-protonx-model/protonx-legal-tc
# MODEL_PATH = os.path.join(root_dir, "local-protonx-model", "protonx-legal-tc")

# ========== OCR CONFIG (DeepDoc + VietOCR) ==========
# Các tham số cấu hình cho DeepDoc+VietOCR engine
OCR_CONFIG = {
    "onnx_dir": os.environ.get("DEEPDOC_ONNX_DIR", 
                               os.path.join(basedir, "deepdoc", "onnx")),
    "vietocr_weight": os.environ.get("VIETOCR_WEIGHT",
                                     os.path.join(basedir, "deepdoc", "vietocr", "weight", "vgg_seq2seq.pth")),
    "drop_score": 0.0,
}

# ========== TEXT CLEANING CONFIG ==========
# LƯU Ý: Với CCCD Mặt trước, extraction được thực hiện qua Traditional hoặc AI Processor.
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

# Từ khóa cho thực đơn (Menu)
MENU_KEYWORDS = [
    "thực đơn", "menu", "giá", "giá tiền", "đồ uống", "món ăn", "món khai vị", "món chính", "khai vị", "giải khát"
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
DEFAULT_PLACE_OF_ISSUE = "CỤC TRƯỞNG CỤC CẢNH SÁT"

# ========== AI API KEY CONFIG ==========
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GERMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash") # Model mặc định tối ưu: nhanh và chính xác nhất cho OCR/Vision RAG


# Hệ số trừ quota khi sử dụng Vision LLM
VISION_LLM_COST = 3

# ========== REDIS CONFIG ==========
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

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


# Email Config
EMAIL_HOST = os.getenv("SMTP_HOST", "")
EMAIL_PORT = os.getenv("SMTP_PORT", "")
EMAIL_USER = os.getenv("SMTP_USERNAME", "")
EMAIL_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")

# ========== SAAS PLANS CONFIG ==========
# 0: free, 1: basic, 2: pro, 3: business, 4: chatbot
PLANS_CONFIG = {
    0: {
        'name': 'Free',
        'description': 'Gói dùng thử cho cá nhân',
        'max_requests_per_month': 10,
        'max_users': 1,
        'price': 0,
        'is_unlimited': False,
        'features': ['10 lượt/tháng', '1 tài khoản', 'Dữ liệu lưu 7 ngày']
    },
    1: {
        'name': 'Basic',
        'description': 'Phù hợp cho cửa hàng nhỏ',
        'max_requests_per_month': 500,
        'max_users': 3,
        'price': 99000,
        'is_unlimited': False,
        'features': ['500 lượt/tháng', '3 tài khoản', 'Dữ liệu lưu 30 ngày', 'Hỗ trợ email']
    },
    2: {
        'name': 'Pro',
        'description': 'Dành cho doanh nghiệp vừa',
        'max_requests_per_month': 1500,
        'max_users': 5,
        'price': 199000,
        'is_unlimited': False,
        'features': ['1.500 lượt/tháng', '5 tài khoản', 'Dữ liệu lưu 90 ngày', 'Hỗ trợ 24/7']
    },
    3: {
        'name': 'Business',
        'description': 'Giải pháp may đo theo yêu cầu',
        'max_requests_per_month': -1,
        'max_users': -1,
        'price': -1, # Liên hệ
        'is_unlimited': True,
        'features': ['Không giới hạn', 'Không giới hạn người dùng', 'Priority support', 'Tùy biến riêng']
    },
    4: {
        'name': 'Chatbot',
        'description': 'Gói dành riêng cho chatbot, giới hạn 5.000 lượt/tháng',
        'max_requests_per_month': 6000,
        'max_users': 1,
        'price': 0,
        'is_unlimited': False,
        'features': ['6.000 lượt/tháng', '1 tài khoản', 'Dành riêng cho chatbot']
    }
}

AUTH_API_URL = os.getenv("AUTH_SERVICE_URL", "")
SYSTEM_ID = os.getenv("SYSTEM_ID", "5efc2c21-b02e-4c8f-965b-1e01d7384a51")
LICENSE_FILENAME = os.getenv("LICENSE_FILENAME", "license.online-docx-ai-quet-tai-lieu.config")
LICENSE_CONFIG_PATH = os.path.join(".licensekek", LICENSE_FILENAME)



# ========== EXTERNAL FILES API CONFIG ==========
FILES_API_URL = os.getenv("FILES_API_URL", "https://files.bittechx.cloud")
FILES_API_UPLOAD_ENDPOINT = os.getenv("FILES_API_UPLOAD_ENDPOINT", "/api/files/upload")
FILES_API_SYSTEM_ID = os.getenv("FILES_API_SYSTEM_ID", "5efc2c21-b02e-4c8f-965b-1e01d7384a51")
FILES_API_USER_ID = os.getenv("FILES_API_USER_ID", "51202")
FILES_API_ALIAS = os.getenv("FILES_API_ALIAS", "home")
FILES_API_KEY = os.getenv("FILES_API_KEY", "client_ecad0526a48d4595a59fba330896feb3")


CCCD_PROVINCE_CODE_MAP = {
    "001": "Hà Nội",
    "002": "Hà Giang",
    "004": "Cao Bằng",
    "006": "Bắc Kạn",
    "008": "Tuyên Quang",
    "010": "Lào Cai",
    "011": "Điện Biên",
    "012": "Lai Châu",
    "014": "Sơn La",
    "015": "Yên Bái",
    "017": "Hoà Bình",
    "019": "Thái Nguyên",
    "020": "Lạng Sơn",
    "022": "Quảng Ninh",
    "024": "Bắc Giang",
    "025": "Phú Thọ",
    "026": "Vĩnh Phúc",
    "027": "Bắc Ninh",
    "030": "Hải Dương",
    "031": "Hải Phòng",
    "033": "Hưng Yên",
    "034": "Thái Bình",
    "035": "Hà Nam",
    "036": "Nam Định",
    "037": "Ninh Bình",
    "038": "Thanh Hoá",
    "040": "Nghệ An",
    "042": "Hà Tĩnh",
    "044": "Quảng Bình",
    "045": "Quảng Trị",
    "046": "Thừa Thiên Huế",
    "048": "Đà Nẵng",
    "049": "Quảng Nam",
    "051": "Quảng Ngãi",
    "052": "Bình Định",
    "054": "Phú Yên",
    "056": "Khánh Hoà",
    "058": "Ninh Thuận",
    "060": "Bình Thuận",
    "062": "Kon Tum",
    "064": "Gia Lai",
    "066": "Đắk Lắk",
    "067": "Đắk Nông",
    "068": "Lâm Đồng",
    "070": "Bình Phước",
    "072": "Tây Ninh",
    "074": "Bình Dương",
    "075": "Đồng Nai",
    "077": "Bà Rịa - Vũng Tàu",
    "079": "TP. Hồ Chí Minh",
    "080": "Long An",
    "082": "Tiền Giang",
    "083": "Bến Tre",
    "084": "Trà Vinh",
    "086": "Vĩnh Long",
    "087": "Đồng Tháp",
    "089": "An Giang",
    "091": "Kiên Giang",
    "092": "Cần Thơ",
    "093": "Hậu Giang",
    "094": "Sóc Trăng",
    "095": "Bạc Liêu",
    "096": "Cà Mau"
}

