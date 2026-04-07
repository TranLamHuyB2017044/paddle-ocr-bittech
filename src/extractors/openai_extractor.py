import os
import json
import base64
from typing import Optional
from openai import OpenAI
from src.config import OPENAI_API_KEY
from src.utils.logger import Log
from src.models.schemas import IdCard, DriverLicense, Invoice, Document, VehicleDocument, RestaurantMenu, MessageAnalysis

# Map doc_type string to Pydantic model
SCHEMA_MAP = {
    "idCard": IdCard,
    "driverLicense": DriverLicense,
    "invoice": Invoice,
    "document": Document,
    "vehicleDocuments": VehicleDocument,
    "menu": RestaurantMenu,
    "message_analysis": MessageAnalysis,
}

class OpenAIExtractor:
    def __init__(self):
        if not OPENAI_API_KEY:
            Log.warning("[OPENAI] ⚠️ Warning: OPENAI_API_KEY is not set. Check .env file.")
            self.client = None
        else:
            try:
                self.client = OpenAI(api_key=OPENAI_API_KEY)
                Log.info("[OPENAI] ✅ OpenAI Client initialized successfully.")
            except Exception as e:
                Log.error(f"[OPENAI] ❌ Error configuring OpenAI Client: {e}")
                self.client = None

    def _get_system_message(self, doc_type):
        """Helper to get system prompt based on doc_type"""
        system_content = "Bạn là chuyên gia trích xuất dữ liệu từ hình ảnh trung thực. Quy tắc:\n1. Không bịa đặt: Thiếu dữ liệu trả về null.\n"
        if doc_type in ['menu', 'invoice', 'vehicleDocuments']:
            system_content += (
                "2. Sửa lỗi chính tả chọn lọc: BẠN CHỈ ĐƯỢC PHÉP thêm dấu và sửa lỗi chính tả cho các từ tiếng Việt.\n"
                "3. Giữ nguyên từ tiếng nước ngoài: TUYỆT ĐỐI KHÔNG dịch, KHÔNG bóp méo, và KHÔNG sửa lỗi chính tả đối với các ký tự/từ ngữ không phải tiếng Việt (ví dụ: tiếng Anh, tên món ăn nước ngoài, ký hiệu đặc biệt). Phải giữ nguyên văn bản gốc cho các từ này.\n"
                "4. Giữ nguyên các thông số số liệu (giá tiền, số lượng, mã số)."
            )
        else:
            system_content += (
                "2. Nguyên tắc sửa lỗi: ĐƯỢC PHÉP và CẦN PHẢI khôi phục dấu tiếng Việt bị thiếu cho phần 'Họ và Tên' và địa danh hành chính (Tỉnh/Huyện/Xã) do lỗi OCR. TUYỆT ĐỐI không sửa các số liệu (số ID, ngày tháng).\n"
                "3. Xử lý xuống dòng: Kết hợp các dòng văn bản bị rời rạc của địa chỉ thành một chuỗi logic, đúng thứ tự hành chính. Không được tự ý thêm bớt thông tin nếu không có trong text gốc.\n"
                "4. Không suy đoán: Tuyệt đối không tự ý điền thông tin (ngẫu nhiên) nếu text gốc bị mờ/mất chữ. Nếu không chắc chắn, trả về null.\n"
                "5. Xử lý Họ Tên: Dựa vào các chữ cái gốc từ OCR, hãy ráp thêm dấu tiếng Việt chuẩn xác và hợp lý nhất (VD: NGUYEN VAN A -> NGUYỄN VĂN A), nhưng giữ nguyên các chữ cái gốc."
            )
        return system_content

    def _get_prompt(self, doc_type):
        """Helper to read prompt from file"""
        prompt_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts')
        prompt_file = f"{doc_type}.md"
        prompt_path = os.path.join(prompt_dir, prompt_file)

        if not os.path.exists(prompt_path):
             Log.error(f"[OPENAI] ❌ Prompt file not found: {prompt_path}")
             return None
             
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            Log.warning(f"[OPENAI] ⚠️ Could not read prompt file: {e}.")
            return None

    def extract(self, text_lines, doc_type):
        """Traditional OCR-text based extraction"""
        if not self.client:
            return {"data": {}, "metadata": {}}

        text_block = "\n".join(text_lines)
        prompt_template = self._get_prompt(doc_type)
        if not prompt_template: return {"data": {}, "metadata": {}}
        
        prompt = f"{prompt_template}\n\nINPUT DATA (OCR TEXT):\n{text_block}"
        response_schema = SCHEMA_MAP.get(doc_type)

        Log.info(f"[OPENAI] 🚀 Sending Text-based request ({doc_type})...")
        try:
            completion = self.client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": self._get_system_message(doc_type)},
                    {"role": "user", "content": prompt},
                ],
                response_format=response_schema,
                temperature=0,
            )
            return self._process_completion(completion)
        except Exception as e:
            Log.error(f"[OPENAI] ❌ OpenAI Error: {e}")
            raise e

    def extract_with_vision(self, image_path, doc_type):
        """VLM-based extraction: Sending IMAGE directly to AI"""
        if not self.client:
            return {"data": {}, "metadata": {}}

        # 1. Encode image
        try:
            with open(image_path, "rb") as image_file:
                base64_image = base64.b64encode(image_file.read()).decode('utf-8')
        except Exception as e:
            Log.error(f"[OPENAI-VLM] ❌ Error encoding image: {e}")
            return {"data": {}, "metadata": {}}

        prompt_template = self._get_prompt(doc_type)
        if not prompt_template: return {"data": {}, "metadata": {}}
        
        response_schema = SCHEMA_MAP.get(doc_type)

        Log.info(f"[OPENAI-VLM] 👁️ Sending Vision-based request ({doc_type})...")
        try:
            completion = self.client.beta.chat.completions.parse(
                model="gpt-4o-mini", # Support Vision by default
                messages=[
                    {"role": "system", "content": self._get_system_message(doc_type)},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": f"{prompt_template}\n\nHãy trích xuất dữ liệu từ hình ảnh đính kèm theo cấu trúc đã định nghĩa."},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}",
                                    "detail": "high"
                                },
                            },
                        ],
                    }
                ],
                response_format=response_schema,
                temperature=0,
            )
            return self._process_completion(completion)
        except Exception as e:
            Log.error(f"[OPENAI-VLM] ❌ OpenAI Error: {e}")
            raise e

    def _process_completion(self, completion):
        """Helper to process completion result"""
        message = completion.choices[0].message
        data = message.parsed.model_dump(mode='json', by_alias=True) if message.parsed else {}
        metadata = {
            "prompt_tokens": completion.usage.prompt_tokens,
            "completion_tokens": completion.usage.completion_tokens,
            "total_tokens": completion.usage.total_tokens,
        }
        return {"data": data, "metadata": metadata}

    def _parse_vietnamese_amount(self, text: Optional[str]) -> Optional[float]:
        """Helper to parse Vietnamese amount strings like '200tr', '5 triệu', '100k' to float."""
        if not text: return None
        try:
            # Clean string: remove commas, dots (except decimal), and spaces
            text = text.lower().replace(',', '').replace(' ', '')
            
            # Define multipliers
            multipliers = {
                'tr': 1_000_000,
                'triệu': 1_000_000,
                'trieu': 1_000_000,
                'k': 1_000,
                'ngàn': 1_000,
                'nghin': 1_000,
                'nghìn': 1_000,
                'tỉ': 1_000_000_000,
                'tỷ': 1_000_000_000,
                'vnđ': 1,
                'đ': 1,
                'd': 1
            }
            
            # Find numeric part and unit part
            match = re.search(r'(\d+\.?\d*)\s*(.*)', text)
            if match:
                number = float(match.group(1))
                unit = match.group(2)
                
                # Apply multiplier if unit found
                for u, m in multipliers.items():
                    if u in unit:
                        return number * m
                return number
        except:
            pass
        return None

    def analyze_message(self, message: str, sender_name: Optional[str] = None):
        """Optimized message analysis with Regex Fast-Path (Hybrid) and Amount Parsing"""
        if not self.client:
            return {"data": {}, "metadata": {}}

        import re
        from datetime import datetime, timezone, timedelta

        # 1. Fast-Path Setup (Regex)
        pre_extracted = {"date": None, "amount": None, "intent": None}
        msg_lower = message.lower()
        
        # Bắt giá tiền (ví dụ: 200tr, 5 triệu, 500k)
        amount_match = re.search(r'(\d+[\s.,]?\d*\s?(?:tr|triệu|k|vnđ|đ|usd|tỉ|tỷ|ngàn|nghìn))', message, re.IGNORECASE)
        if amount_match:
            pre_extracted["amount"] = self._parse_vietnamese_amount(amount_match.group(1))

        # Bắt ngày tháng đơn giản (dd/mm/yyyy hoặc dd-mm-yyyy)
        date_match = re.search(r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})', message)
        if date_match:
            pre_extracted["date"] = date_match.group(1)

        # Bắt Intent qua từ khóa (Fast detection)
        if any(k in msg_lower for k in ["nghỉ", "nghỉ phép", "xin nghỉ", "off"]):
            pre_extracted["intent"] = "leave_request"
        elif any(k in msg_lower for k in ["báo giá", "giá", "quotation", "chốt giá"]):
            pre_extracted["intent"] = "quotation"
        elif any(k in msg_lower for k in ["công tác", "business trip", "đi công tác"]):
            pre_extracted["intent"] = "business_trip"

        # 2. Context & Current Time
        utc_plus_7 = timezone(timedelta(hours=7))
        current_time_dt = datetime.now(utc_plus_7)
        current_time_str = current_time_dt.strftime("%H:%M:%S, %d-%m-%Y")

        # 3. Fast-Path Decision (If intent is clear and message is simple)
        if pre_extracted["intent"] and len(message) < 60:
            # Kiểm tra nếu đủ metadata tối thiểu để trả kết quả ngay
            is_fast_path = False
            if pre_extracted["intent"] == "leave_request":
                # Nghỉ phép cần date, nếu không có regex bắt được, mặc định là ngày hiện tại hoặc mai (nếu có từ 'mai')
                if "mai" in msg_lower:
                    tomorrow = current_time_dt + timedelta(days=1)
                    pre_extracted["date"] = tomorrow.strftime("%H:%M:%S, %d-%m-%Y")
                elif not pre_extracted["date"]:
                    pre_extracted["date"] = current_time_str
                is_fast_path = True
            elif pre_extracted["intent"] == "quotation" and pre_extracted["amount"]:
                # Báo giá cần amount
                if not pre_extracted["date"]: pre_extracted["date"] = current_time_str
                is_fast_path = True

            if is_fast_path:
                Log.info(f"[HYBRID] 🚀 Fast-Path Hit (Regex)! Latency: <10ms")
                return {
                    "data": {
                        "intent": pre_extracted["intent"],
                        "confidence": 0.98,
                        "metadata": {
                            "date": pre_extracted["date"],
                            "customer_name": sender_name if pre_extracted["intent"] == "leave_request" else None,
                            "amount": pre_extracted["amount"]
                        }
                    },
                    "metadata": {"source": "regex_fast_path"}
                }

        # 4. Fallback to OpenAI (If Fast-Path missed)
        prompt_template = self._get_prompt("message_analysis")
        if not prompt_template: return {"data": {}, "metadata": {}}

        context_parts = [f"Time: {current_time_str}"]
        if sender_name: context_parts.append(f"Sender: {sender_name}")
        if pre_extracted["amount"]: context_parts.append(f"Regex_Amount: {pre_extracted['amount']}")
        if pre_extracted["date"]: context_parts.append(f"Regex_Date: {pre_extracted['date']}")
        
        user_prompt = f"Context: {', '.join(context_parts)}\nPrompt: {prompt_template}\nInput: {message}"

        Log.info(f"[OPENAI] ⚡ Calling AI (Fast-Path Missed)...")
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Fast Vietnamese message analyzer. Intent MUST be leave_request, business_trip, or quotation. Else return null. Output JSON only."},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0,
                max_tokens=150,
            )
            
            content = response.choices[0].message.content or "{}"
            data = json.loads(content)
            
            # Bắt buộc chuyển amount về float nếu AI trả về string
            if data.get("metadata", {}).get("amount"):
                raw_amt = data["metadata"]["amount"]
                if isinstance(raw_amt, str):
                    data["metadata"]["amount"] = self._parse_vietnamese_amount(raw_amt)
            
            # Combine Regex results if AI missed them
            if not data.get("metadata", {}).get("amount") and pre_extracted["amount"]:
                data.setdefault("metadata", {})["amount"] = pre_extracted["amount"]
            
            # Đảm bảo intent là null nếu không thuộc 3 loại yêu cầu
            allowed_intents = ["leave_request", "business_trip", "quotation"]
            if data.get("intent") not in allowed_intents:
                data["intent"] = None

            return {
                "data": data, 
                "metadata": {
                    "source": "openai",
                    "usage": {
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                        "total_tokens": response.usage.total_tokens
                    }
                }
            }
        except Exception as e:
            Log.error(f"[OPENAI] ❌ Analysis Error: {e}")
            raise e

# Global instance
openai_extractor = OpenAIExtractor()

# Global instance
openai_extractor = OpenAIExtractor()
