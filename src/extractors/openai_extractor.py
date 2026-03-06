import os
import json
import base64
from typing import Optional
from openai import OpenAI
from src.config import OPENAI_API_KEY
from src.utils.logger import Log
from src.models.schemas import IdCard, DriverLicense, Invoice, Document, VehicleDocument, RestaurantMenu

# Map doc_type string to Pydantic model
SCHEMA_MAP = {
    "idCard": IdCard,
    "driverLicense": DriverLicense,
    "invoice": Invoice,
    "document": Document,
    "vehicleDocuments": VehicleDocument,
    "menu": RestaurantMenu
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
                "2. Sửa lỗi chính tả: Được phép sửa lỗi chính tả, thêm dấu tiếng Việt cho tên sản phẩm, tên quán, "
                "địa chỉ và các nội dung văn bản để đúng ngữ pháp/chính tả tiếng Việt.\n"
                "3. Giữ nguyên các thông số số liệu (giá tiền, số lượng, mã số)."
            )
        else:
            system_content += (
                "2. Khôi phục dấu: Chỉ thêm dấu cho Họ Tên, Địa chỉ và Quê quán phổ biến để đúng chính tả tiếng Việt. "
                "Giữ nguyên nếu là tên lạ/dân tộc.\n"
                "3. Tuyệt đối không thay đổi chữ cái gốc của văn bản."
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

# Global instance
openai_extractor = OpenAIExtractor()

# Global instance
openai_extractor = OpenAIExtractor()
