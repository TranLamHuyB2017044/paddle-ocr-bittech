"""
Back Extractor
Trích xuất thông tin từ mặt sau CCCD
"""
import re
from cccd.config import DEFAULT_PLACE_OF_ISSUE


def extract_back(texts):
    """
    Trích xuất thông tin từ mặt sau CCCD
    
    Args:
        texts: Danh sách các dòng text đã được làm sạch
        
    Returns:
        dict: Thông tin đã trích xuất
    """
    info = {
        "dateOfIssue": "",
        "placeOfIssue": DEFAULT_PLACE_OF_ISSUE
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
