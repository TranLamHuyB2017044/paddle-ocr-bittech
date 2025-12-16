from src.utils.smart_extractor import SmartExtractor
from src.models.schemas import IdCard, DriverLicense, Invoice, Document
from src.config import COMMON_COUNTRIES_REGEX

# ==================== ID CARD (CCCD) CONFIG ====================
CCCD_CONFIG = {
    "idNumber": {
        "keywords": ["số", "so", "id no", "no.", "số đd cn", "S/No"],
        "keywords_threshold": 0.9,
        "value_regex": r"\d{9,12}",
        "extraction_mode": "next_line",
        "global_regex": True
    },
    "fullName": {
        "keywords": ["họ và tên", "họ tên", "full name"],
        "keywords_threshold": 0.8,
        "value_regex": r"^[A-ZÀ-Ỹ ]{2,}$", 
        "extraction_mode": "auto"
    },
    "dob": {
        "keywords": ["ngày, tháng, năm sinh", "ngày sinh", "date of birth", "dob"],
        "keywords_threshold": 0.7,
        "value_regex": r"\d{2}[-/]\d{2}[-/]\d{4}",
        "extraction_mode": "auto"
    },
    "gender": {
        "keywords": ["giới tính", "sex", "gender"],
        "keywords_threshold": 0.8,
        "value_regex": r"^(Nam|Nữ|Male|Female)$",
        "extraction_mode": "auto"
    },
    "nationality": {
        "keywords": ["quốc tịch", "nationality"],
        "keywords_threshold": 0.8,
        "value_regex": COMMON_COUNTRIES_REGEX,
        "extraction_mode": "auto",
        "global_regex": True
    },
    "hometown": {
        "keywords": ["quê quán", "place of origin"],
        "keywords_threshold": 0.8,
        "value_regex": None,
        "extraction_mode": "multiline",
        "max_lines": 2
    },
    "address": {
        "keywords": ["nơi thường trú", "place of residence"],
        "keywords_threshold": 0.8,
        "value_regex": None,
        "extraction_mode": "multiline",
        "max_lines": 2
    },
    "expiryDate": {
        "keywords": ["có giá trị đến", "date of expiry", "giá trị đến"],
        "keywords_threshold": 0.8,
        "value_regex": r"\d{2}[-/]\d{2}[-/]\d{4}",
        "extraction_mode": "auto"
    },
    "dateOfIssue": {
        "keywords": ["ngày, tháng, năm", "ngày cấp", "date of issue"], # Often on back side
        "keywords_threshold": 0.7,
        "value_regex": r"\d{2}[-/]\d{2}[-/]\d{4}",
        "extraction_mode": "auto"
    },
    "placeOfIssue": {
        "keywords": ["cục trưởng", "director"], # Heuristic for place of issue anchor
        "keywords_threshold": 0.7,
        "value_regex": None,
        "extraction_mode": "same_line" # Or next_line depending on layout
    }
}

# ==================== DRIVER LICENSE CONFIG ====================
DRIVER_LICENSE_CONFIG = {
    "idNumber": {
        "keywords": ["số", "no."],
        "keywords_threshold": 0.8,
        "value_regex": r"^\d+$",
        "extraction_mode": "same_line"
    },
    "fullName": {
        "keywords": ["họ tên", "full name"],
        "keywords_threshold": 0.8,
        "value_regex": r"^[A-ZÀ-Ỹ ]{2,}$",
        "extraction_mode": "next_line"
    },
    "dob": {
        "keywords": ["ngày sinh", "date of birth"],
        "keywords_threshold": 0.8,
        "value_regex": r"\d{2}[-/]\d{2}[-/]\d{4}",
        "extraction_mode": "auto"
    },
    "rank": { # Mapped to 'class' via alias in schema or direct key
        "keywords": ["hạng", "class"],
        "keywords_threshold": 0.8,
        "value_regex": r"^[A-Z][0-9]?$",
        "extraction_mode": "same_line"
    },
    "nationality": {
        "keywords": ["quốc tịch", "nationality"],
        "keywords_threshold": 0.8,
        "value_regex": COMMON_COUNTRIES_REGEX,
        "extraction_mode": "auto",
        "global_regex": True
    },
    "address": {
        "keywords": ["nơi cư trú", "address"],
        "keywords_threshold": 0.8,
        "value_regex": None,
        "extraction_mode": "next_line"
    },
    "expiryDate": {
        "keywords": ["có giá trị đến", "expires"],
        "keywords_threshold": 0.8,
        "value_regex": r"\d{2}[-/]\d{2}[-/]\d{4}",
        "extraction_mode": "auto"
    },
    "dateOfIssue": {
        "keywords": ["ngày", "date"], # Often combined
        "keywords_threshold": 0.7,
        "value_regex": r"\d{2}[-/]\d{2}[-/]\d{4}",
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
