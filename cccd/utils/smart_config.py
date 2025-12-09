from cccd.utils.smart_extractor import SmartExtractor
from cccd.models.schemas import IdCard, DriverLicense, Invoice, Document
from cccd.config import (
    DATE_KEYWORDS,
    FRONT_KEYWORDS,
    ADDRESS_KEYWORDS,
    EXPIRY_LABEL_KEYWORDS,
    HOMETOWN_KEYWORDS
)

# ==================== ID CARD (CCCD) CONFIG ====================
CCCD_CONFIG = {
    "idNumber": {
        "keywords": ["số", "id no", "no.", "số cccd", "số định danh"],
        "keywords_threshold": 0.92,            # tăng ngưỡng để tránh match sai chữ "số"
        "value_regex": r"\b\d{9,12}\b",
        "extraction_mode": "same_line"
    },

    "fullName": {
        "keywords": FRONT_KEYWORDS, # Use imported keywords
        "keywords_threshold": 0.75,
        "value_regex": r"[A-ZÀ-Ỹ ]{3,}",
        "extraction_mode": "next_line"
    },

    "dob": {
        "keywords": ["ngày sinh", "date of birth", "dob"] + DATE_KEYWORDS,
        "keywords_threshold": 0.7,
        "value_regex": r"\b\d{2}[/-]\d{2}[/-]\d{4}\b",
        "extraction_mode": "next_line"
    },

    "gender": {
        "keywords": ["giới tính", "gender", "sex"],
        "keywords_threshold": 0.7,
        "value_regex": r"(nam|nữ|male|female)",
        "extraction_mode": "auto"
    },

    "nationality": {
        "keywords": ["quốc tịch", "nationality", "viet nam", "vit nam"],
        "keywords_threshold": 0.7,
        "value_regex": None,
        "extraction_mode": "auto"
    },

    "hometown": {
        "keywords": HOMETOWN_KEYWORDS,
        "keywords_threshold": 0.7,
        "value_regex": None,
        "extraction_mode": "multiline",       # ⭐ cho phép nối nhiều dòng
        "max_lines": 3                        # tối đa 3 dòng
    },

    "address": {
        "keywords": ADDRESS_KEYWORDS,
        "keywords_threshold": 0.75,
        "value_regex": None,
        "extraction_mode": "multiline",       # ⭐
        "max_lines": 3
    },

    "expiryDate": {
        "keywords": EXPIRY_LABEL_KEYWORDS + ["date of expiry", "expires"],
        "keywords_threshold": 0.7,
        "value_regex": r"\b\d{2}[/-]\d{2}[/-]\d{4}\b",
        "extraction_mode": "auto"
    },

    "dateOfIssue": {
        "keywords": ["ngày cấp", "date of issue"] + DATE_KEYWORDS,
        "keywords_threshold": 0.7,
        "value_regex": r"\b\d{2}[/-]\d{2}[/-]\d{4}\b",
        "extraction_mode": "auto"
    },

    "placeOfIssue": {
        "keywords": ["cục trưởng", "director", "place of issue"],
        "keywords_threshold": 0.7,
        "value_regex": None,
        "extraction_mode": "same_line"
    }
}


# ==================== DRIVER LICENSE CONFIG ====================
DRIVER_LICENSE_CONFIG = {
    "idNumber": {
        "keywords": ["số", "no", "id no", "driver no"],
        "keywords_threshold": 0.9,
        "value_regex": r"\b\d{9,12}\b",
        "extraction_mode": "same_line"
    },

    "fullName": {
        "keywords": ["họ tên", "full name"],
        "keywords_threshold": 0.75,
        "value_regex": r"[A-ZÀ-Ỹ ]{3,}",
        "extraction_mode": "next_line"
    },

    "nationality": {
        "keywords": ["quốc tịch", "nationality", "vit nam"],
        "keywords_threshold": 0.7,
        "value_regex": None,
        "extraction_mode": "auto"
    },

    "dob": {
        "keywords": ["ngày sinh", "date of birth"],
        "keywords_threshold": 0.7,
        "value_regex": r"\b\d{2}[/-]\d{2}[/-]\d{4}\b",
        "extraction_mode": "next_line"
    },

    "rank": {
        "keywords": ["hạng", "class", "a1", "b1", "b2", "c", "d"],
        "keywords_threshold": 0.7,
        "value_regex": r"[A-Z][0-9]?",
        "extraction_mode": "same_line"
    },

    "expiryDate": {
        "keywords": ["có giá trị đến", "expires"],
        "keywords_threshold": 0.7,
        "value_regex": r"\b\d{2}[/-]\d{2}[/-]\d{4}\b",
        "extraction_mode": "auto"
    },

    "dateOfIssue": {
        "keywords": ["ngày cấp", "date of issue"],
        "keywords_threshold": 0.7,
        "value_regex": r"\b\d{2}[/-]\d{2}[/-]\d{4}\b",
        "extraction_mode": "auto"
    }
}

# ==================== DOCUMENT & INVOICE CONFIG (Example) ====================
INVOICE_CONFIG = {
    "so_hoa_don": {
        "keywords": ["số hóa đơn", "invoice no", "số hd"],
        "keywords_threshold": 0.8,
        "value_regex": None,
        "extraction_mode": "same_line"
    },
    "tong_so_tien": {
        "keywords": ["tổng cộng", "total", "thành tiền"],
        "keywords_threshold": 0.8,
        "value_regex": r"[\d.,]+",
        "extraction_mode": "same_line"
    },
    "ngay_lap_phieu": {
        "keywords": ["ngày", "date"],
        "keywords_threshold": 0.7,
        "value_regex": r"\d{2}[-/]\d{2}[-/]\d{4}",
        "extraction_mode": "auto"
    }
}

DOCUMENT_CONFIG = {
    # Generic document fields usually rely on layout or specific keywords
    "title": {
        # Strategy: usually first few lines?
        # Keyword based title finding is hard.
        "keywords": [],
        "extraction_mode": "auto"
    }
}


# ==================== CONFIG REGISTRY ====================
CONFIG_MAP = {
    "idCard": CCCD_CONFIG,
    "driverLicense": DRIVER_LICENSE_CONFIG,
    "invoice": INVOICE_CONFIG,
    "document": DOCUMENT_CONFIG
}

def get_smart_config(doc_type):
    return CONFIG_MAP.get(doc_type, CCCD_CONFIG)

def smart_extract(lines, doc_type="idCard"):
    """
    Generic smart extraction function for any document type
    """
    config = get_smart_config(doc_type)
    if not config:
        return {}
        
    extractor = SmartExtractor(config)
    return extractor.extract(lines)
