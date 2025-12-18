from src.models.schemas import IdCard, DriverLicense, Invoice, Document
from src.config import COMMON_COUNTRIES_REGEX

# ==================== ID CARD (CCCD) CONFIG ====================
CCCD_CONFIG = {
    "idNumber": {
        "keywords": ["số", "so", "id no", "no.", "số đd cn", "S/No", "s6/No."],
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
        "extraction_mode": "same_line"
    },
    "gender": {
        "keywords": ["giới tính", "sex", "gender"],
        "keywords_threshold": 0.8,
        "value_regex": r"(Nam|Nữ|Male|Female)",
        "extraction_mode": "same_line"
    },
    "nationality": {
        "keywords": ["quốc tịch", "nationality", 'Quc tich', 'Quc tch'],
        "keywords_threshold": 0.8,
        "value_regex": COMMON_COUNTRIES_REGEX,
        "extraction_mode": "auto",
        "global_regex": True
    },
    "hometown": {
        "keywords": ["quê quán", "place of origin"],
        "keywords_threshold": 0.8,
        "value_regex": None,
        "extraction_mode": "auto",
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
        "keywords": ["Date of", "có giá trị đến", "date of expiry", "giá trị đến", "Date of expiration", "expiration"],
        "keywords_threshold": 0.8,
        "value_regex": r"\d{2}[-/]\d{2}[-/]\d{4}",
        "extraction_mode": "auto"
    },
    "dateOfIssue": {
        "keywords": ["ngày, tháng, năm", "ngày cấp", "date of issue", 'Date, month, year.'], # Often on back side
        "keywords_threshold": 0.7,
        "value_regex": r"\d{2}[-/]\d{2}[-/]\d{4}",
        "extraction_mode": "same_line"
    },
    "placeOfIssue": {
        "keywords": ["cục trưởng", "director"], # Heuristic for place of issue anchor
        "keywords_threshold": 0.7,
        "value_regex": None,
        "extraction_mode": "multiline" # Or next_line depending on layout
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
        "value_regex": r"(\d{2}[-/]\d{2}[-/]\d{4}|không thời hạn|unlimited)",
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
    "ten_hoa_don": {
        "keywords": ["HÓA ĐƠN", "PHIẾU", "RECEIPT", "INVOICE"],
        "keywords_threshold": 0.7,
        "value_regex": None,
        "extraction_mode": "same_line"
    },
    "so_hoa_don": {
        "keywords": ["số hóa đơn", "invoice no", "số hd", "số phiếu", "bill no"],
        "keywords_threshold": 0.8,
        "value_regex": None,
        "extraction_mode": "same_line"
    },
    "ngay_lap_hoa_don": {
        "keywords": ["ngày", "date"],
        "keywords_threshold": 0.7,
        "value_regex": r"\d{2}[-/]\d{2}[-/]\d{4}",
        "extraction_mode": "auto"
    },
    "ten_khach_hang": {
        "keywords": ["khách hàng", "người mua", "tên đơn vị", "customer", "buyer"],
        "keywords_threshold": 0.8,
        "value_regex": None,
        "extraction_mode": "same_line"
    },
    "dia_chi_khach_hang": {
        "keywords": ["địa chỉ", "address"],
        "keywords_threshold": 0.7,
        "value_regex": None,
        "extraction_mode": "auto"
    },
    "ten_nguoi_ban": {
        "keywords": ["đơn vị bán", "nhà cung cấp", "seller"],
        "keywords_threshold": 0.8,
        "value_regex": None,
        "extraction_mode": "same_line"
    },
    "dia_chi_nguoi_ban": {
        "keywords": ["địa chỉ bán", "văn phòng"],
        "keywords_threshold": 0.8,
        "value_regex": None,
        "extraction_mode": "auto"
    },
    "tong_tien": {
        "keywords": ["tổng cộng", "total", "thành tiền", "cộng tiền hàng", "thanh toán"],
        "keywords_threshold": 0.7,
        "value_regex": r"[\d.,]+",
        "extraction_mode": "same_line"
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
