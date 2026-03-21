import json
from openai import OpenAI
from src.config import OPENAI_API_KEY
from src.utils.logger import Log
from src.models.schemas import DocumentCheckResponse

class DocumentCheckExtractor:
    def __init__(self):
        if not OPENAI_API_KEY:
            Log.warning("[CHECK-EXTRACTOR] ⚠️ Warning: OPENAI_API_KEY is not set.")
            self.client = None
        else:
            try:
                self.client = OpenAI(api_key=OPENAI_API_KEY)
                Log.info("[CHECK-EXTRACTOR] ✅ OpenAI Client initialized.")
            except Exception as e:
                Log.error(f"[CHECK-EXTRACTOR] ❌ Error initializing OpenAI Client: {e}")
                self.client = None

    def check_document(self, document_blocks, company_schema_json, doc_type="invoice"):
        """
        Compare document blocks with company schema using GPT-4o.
        """
        if not self.client:
            return None

        system_prompt = """
        Bạn là chuyên gia kiểm tra tài liệu thương mại tiếng Việt.
        So sánh tài liệu khách hàng với dữ liệu chuẩn, phát hiện sai lệch.

        Phân loại lỗi: TYPO | NUMBER_MISMATCH | NAME_MISMATCH | ADDRESS_MISMATCH | MISSING_INFO | DATE_MISMATCH
        Mức độ: HIGH (sai số tiền, tên pháp lý, MST) | MEDIUM (sai địa chỉ, ngày) | LOW (typo thuần túy)

        QUY TẮC QUAN TRỌNG:
        1. NGÔN NGỮ: Toàn bộ nội dung trường `explanation` và `note` PHẢI trả về bằng TIẾNG VIỆT (ví dụ: "Mã số thuế người bán bị thiếu").
        2. OCR CORRECTION: Trong trường `text_segment`, nếu phát hiện lỗi chính tả do máy đọc OCR (ví dụ: "Còng ty", "Thái Son"), hãy TỰ ĐỘNG SỬA thành đúng chính tả tiếng Việt ("Công ty", "Thái Sơn") để người dùng dễ đọc, nhưng KHÔNG ĐƯỢC thay đổi từ ngữ gốc của tài liệu.
        3. Format số tiền khác nhau (15.000.000đ = 15,000,000 VND) → KHÔNG phải lỗi.
        4. Viết tắt địa danh phổ biến (TP.HCM, Q.1) → KHÔNG phải lỗi.
        5. Thông tin thừa → warnings, không phải errors.
        6. Sai tên riêng dù 1 ký tự → HIGH ERROR.
        7. Sai 1 chữ số trong dữ liệu quan trọng → HIGH ERROR.

        Chỉ trả về JSON hợp lệ, không có text ngoài JSON.
        """
        
        doc_type_labels = {
            "invoice": "Hóa đơn",
            "contract": "Hợp đồng",
            "delivery": "Biên bản giao hàng"
        }
        doc_type_label = doc_type_labels.get(doc_type, doc_type)

        user_prompt = f"""
Loại tài liệu: {doc_type_label}

Dữ liệu chuẩn công ty (JSON):
{company_schema_json}

Tài liệu khách hàng:
Mỗi dòng format: [Trang X | Dòng Y | bbox:(x1,y1,x2,y2)] <nội dung>
{document_blocks}

Kiểm tra từng field trong schema. Trả về JSON:
{{
  "status": "PASS" | "FAIL",
  "summary": {{
    "total_errors": 0,
    "error_breakdown": {{ "TYPO":0, "NUMBER_MISMATCH":0, "NAME_MISMATCH":0,
                         "ADDRESS_MISMATCH":0, "MISSING_INFO":0, "DATE_MISMATCH":0 }}
  }},
  "errors": [{{
    "error_id": "ERR_001",
    "type": "...",
    "severity": "HIGH|MEDIUM|LOW",
    "field": "<field trong schema>",
    "location": {{ "page":1, "line":5, "bbox":[x1,y1,x2,y2], "text_segment":"..." }},
    "found_value": "...",
    "expected_value": "...",
    "explanation": "..."
  }}],
  "warnings": [{{
    "type": "EXTRA_INFO",
    "location": {{ "page":1, "line":3, "text_segment":"..." }},
    "note": "..."
  }}]
}}
"""

        try:
            Log.info(f"[CHECK-EXTRACTOR] 🚀 Sending request to GPT-4o (Type: {doc_type})...")
            completion = self.client.beta.chat.completions.parse(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format=DocumentCheckResponse,
                temperature=0,
            )
            
            message = completion.choices[0].message
            usage = completion.usage
            
            if message.parsed:
                return message.parsed.model_dump(mode='json', by_alias=True), usage
            else:
                Log.error("[CHECK-EXTRACTOR] ❌ Failed to parse GPT-4o response.")
                return None, usage
                
        except Exception as e:
            Log.error(f"[CHECK-EXTRACTOR] ❌ OpenAI Error: {e}")
            return None, None

# Global instance
document_check_extractor = DocumentCheckExtractor()
