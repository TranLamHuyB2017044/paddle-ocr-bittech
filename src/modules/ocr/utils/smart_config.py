from src.modules.ocr.models.schemas import IdCard, DriverLicense, Invoice, Document
from src.core.config import COMMON_COUNTRIES_REGEX

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
    "title": {
        "keywords": [],
        "extraction_mode": "auto"
    }
}

# ==================== VEHICLE DOCUMENTS CONFIG ====================
VEHICLE_DOC_CONFIG = {
    "plateNumber": {
        "keywords": ["biển số", "số đăng ký", "plate no", "number plate"],
        "keywords_threshold": 0.8,
        "value_regex": r"[0-9]{2}[A-Z]-[0-9]{3,5}(\.[0-9]{2})?", # Simplified VN plate regex
        "extraction_mode": "auto"
    },
    "ownerName": {
        "keywords": ["chủ xe", "tên chủ xe", "người được bảo hiểm", "owner's full name", "người mua"],
        "keywords_threshold": 0.8,
        "extraction_mode": "next_line"
    },
    "engineNumber": {
        "keywords": ["số máy", "engine no", "engine number"],
        "keywords_threshold": 0.8,
        "extraction_mode": "auto"
    },
    "chassisNumber": {
        "keywords": ["số khung", "chassis no", "chassis number", "số xe"],
        "keywords_threshold": 0.8,
        "extraction_mode": "auto"
    },
    "inspectionNumber": {
        "keywords": ["số phiếu kiểm định", "số đăng kiểm", "inspection report no"],
        "keywords_threshold": 0.8,
        "value_regex": r"VA-[0-9]+",
        "extraction_mode": "auto"
    },
    "dateOfIssue": {
        "keywords": ["ngày cấp", "issued on", "ngày đăng ký lần đầu"],
        "keywords_threshold": 0.8,
        "value_regex": r"\d{2}[-/]\d{2}[-/]\d{4}",
        "extraction_mode": "auto"
    },
    "expiryDate": {
        "keywords": ["hết hạn ngày", "có hiệu lực đến ngày", "valid until", "đến ngày", "đến 15 giờ 00, ngày"],
        "keywords_threshold": 0.7,
        "value_regex": r"\d{2}[-/]\d{2}[-/]\d{4}",
        "extraction_mode": "auto"
    },
    "effectiveDate": {
        "keywords": ["hiệu lực từ ngày", "từ 15 giờ 00, ngày", "valid from"],
        "keywords_threshold": 0.7,
        "value_regex": r"\d{2}[-/]\d{2}[-/]\d{4}",
        "extraction_mode": "auto"
    }
}


# ==================== ADMINISTRATIVE DOCUMENT CONFIG ====================
ADMINISTRATIVE_DOC_CONFIG = {
    "documentNo": {
        "keywords": ["số:", "số", "ký hiệu", "số/ký hiệu"],
        "keywords_threshold": 0.8,
        "extraction_mode": "auto"
    },
    "senderOrg": {
        "keywords": ["ủy ban nhân dân", "ubnd", "bộ", "sở", "cục", "ban"],
        "keywords_threshold": 0.7,
        "extraction_mode": "auto"
    },
    "title": {
        "keywords": ["v/v", "về việc", "trích yếu"],
        "keywords_threshold": 0.8,
        "extraction_mode": "auto"
    },
    "issueDate": {
        "keywords": ["ngày", "tháng", "năm"],
        "keywords_threshold": 0.7,
        "value_regex": r"\d{2}[-/]\d{2}[-/]\d{4}",
        "extraction_mode": "auto"
    },
    "receiveDate": {
        "keywords": ["ngày đến", "đến ngày", "ngày nhận"],
        "keywords_threshold": 0.7,
        "value_regex": r"\d{2}[-/]\d{2}[-/]\d{4}",
        "extraction_mode": "auto"
    },
    "deadline": {
        "keywords": ["hạn xử lý", "trước ngày", "thời hạn"],
        "keywords_threshold": 0.7,
        "value_regex": r"\d{2}[-/]\d{2}[-/]\d{4}",
        "extraction_mode": "auto"
    }
}


# ==================== CONFIG REGISTRY ====================
CONFIG_MAP = {
    "idCard": CCCD_CONFIG,
    "driverLicense": DRIVER_LICENSE_CONFIG,
    "invoice": INVOICE_CONFIG,
    "administrativeDocument": ADMINISTRATIVE_DOC_CONFIG,
    "vehicleDocuments": VEHICLE_DOC_CONFIG,
    "menu": {"business_name": {"keywords": ["thực đơn", "menu"], "extraction_mode": "auto"}},
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
