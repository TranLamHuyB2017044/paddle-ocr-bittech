import os
import json
import base64
import re
from typing import Optional
from openai import OpenAI
from src.core.config import OPENAI_API_KEY
from src.shared.utils.logger import Log
from src.modules.ocr.models.schemas import IdCard, DriverLicense, Invoice, Document, VehicleDocument, RestaurantMenu, MessageAnalysis, AdministrativeDocument

# Map doc_type string to Pydantic model
SCHEMA_MAP = {
    "idCard": IdCard,
    "driverLicense": DriverLicense,
    "invoice": Invoice,
    "administrativeDocument": AdministrativeDocument,
    "vehicleDocuments": VehicleDocument,
    "menu": RestaurantMenu,
    "message_analysis": MessageAnalysis,
}

class OpenAIExtractor:
    def __init__(self):
        self.client = None
        if not OPENAI_API_KEY:
            Log.warning("[OPENAI] ⚠️ Warning: OPENAI_API_KEY is not set.")
        else:
            try:
                self.client = OpenAI(api_key=OPENAI_API_KEY)
                Log.info("[OPENAI] ✅ OpenAI Client initialized successfully.")
            except Exception as e:
                Log.error(f"[OPENAI] ❌ Error configuring OpenAI Client: {e}")

    def _get_system_message(self, doc_type):
        """Tối ưu Token: Chỉ để lại chỉ thị cốt lõi nhất."""
        return "Bạn là trợ lý trích xuất dữ liệu trung thực. Chỉ trích xuất thông tin từ đầu vào, không suy đoán. Trả về null nếu thiếu."

    def _get_prompt(self, doc_type):
        """Đọc Prompt từ file .md trong thư mục prompts"""
        prompt_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts')
        prompt_path = os.path.join(prompt_dir, f"{doc_type}.md")

        if not os.path.exists(prompt_path):
             Log.error(f"[OPENAI] ❌ Prompt file not found: {prompt_path}")
             return None
             
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            Log.warning(f"[OPENAI] ⚠️ Could not read prompt file: {e}")
            return None

    def extract(self, text_lines, doc_type):
        """Xử lý trích xuất dựa trên Text OCR (Token Optimized)"""
        if not self.client: 
            return {"data": {}, "metadata": {"error": "client_not_init"}}

        text_block = "\n".join(text_lines).strip()
        
        if not text_block or len(text_block) < 3:
            Log.warning(f"[OPENAI] ⚠️ Input too short for {doc_type}. Skipping...")
            return {"data": {}, "metadata": {"status": "empty_input"}}

        prompt_template = self._get_prompt(doc_type)
        if not prompt_template: 
            return {"data": {}, "metadata": {"error": "prompt_not_found"}}
        
        response_schema = SCHEMA_MAP.get(doc_type)
        if not response_schema:
            Log.error(f"[OPENAI] ❌ Schema not found for doc_type: {doc_type}")
            return {"data": {}, "metadata": {"error": "schema_not_found"}}

        prompt = f"{prompt_template}\n\nINPUT DATA (OCR TEXT):\n{text_block}"

        Log.info(f"[OPENAI] 🚀 Key Extraction for {doc_type}...")
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
            return self._process_completion(completion, doc_type)
        except Exception as e:
            Log.error(f"[OPENAI] ❌ OpenAI Error: {e}")
            raise e

    def extract_with_vision(self, image_paths, doc_type):
        """Vision-based extraction (hỗ trợ nhiều ảnh) - Phương án dự phòng cho Gemini"""
        if not self.client: 
            return {"data": {}, "metadata": {"error": "client_not_init"}}

        # Đảm bảo image_paths luôn là list
        if isinstance(image_paths, str):
            image_paths = [image_paths]

        content_messages = []
        prompt_template = self._get_prompt(doc_type)
        if not prompt_template: 
            return {"data": {}, "metadata": {"error": "prompt_not_found"}}

        content_messages.append(
            {"type": "text", "text": f"{prompt_template}\n\nHãy trích xuất dữ liệu từ các hình ảnh đính kèm."}
        )

        for p in image_paths:
            try:
                with open(p, "rb") as image_file:
                    base64_image = base64.b64encode(image_file.read()).decode('utf-8')
                    content_messages.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                    })
            except Exception as e:
                Log.error(f"[OPENAI-VLM] ❌ Image encoding error for {p}: {e}")

        if len(content_messages) == 1: # Chỉ có text, không load được ảnh nào
            return {"data": {}, "metadata": {"error": "no_valid_images"}}

        response_schema = SCHEMA_MAP.get(doc_type)
        if not response_schema:
            Log.error(f"[OPENAI-VLM] ❌ Schema not found for doc_type: {doc_type}")
            return {"data": {}, "metadata": {"error": "schema_not_found"}}

        Log.info(f"[OPENAI-VLM] 👁️ Vision Extraction cho {doc_type} với {len(image_paths)} ảnh...")
        
        try:
            completion = self.client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": self._get_system_message(doc_type)},
                    {"role": "user", "content": content_messages}
                ],
                response_format=response_schema,
                temperature=0,
            )
            return self._process_completion(completion, doc_type)
        except Exception as e:
            Log.error(f"[OPENAI-VLM] ❌ OpenAI Error: {e}")
            raise e

    def _process_completion(self, completion, doc_type: str):
        """Hậu xử lý kết quả: Chuyển đổi tiền tệ thông minh cho Invoice/Menu"""
        message = completion.choices[0].message
        data = message.parsed.model_dump(mode='json', by_alias=True) if message.parsed else {}
        
        if doc_type in ['invoice', 'menu']:
            currency_fields = ['totalAmount', 'subtotal', 'taxAmount', 'price']
            for field in currency_fields:
                if field in data and isinstance(data[field], str):
                    data[field] = self._parse_vietnamese_amount(data[field])
                if 'items' in data and isinstance(data['items'], list):
                    for item in data['items']:
                        if field in item and isinstance(item[field], str):
                             item[field] = self._parse_vietnamese_amount(item[field])

        metadata = {
            "usage": {
                "prompt_tokens": completion.usage.prompt_tokens,
                "completion_tokens": completion.usage.completion_tokens,
                "total_tokens": completion.usage.total_tokens,
            }
        }
        return {"data": data, "metadata": metadata}

    def _parse_vietnamese_amount(self, text: str) -> Optional[float]:
        if not text: return None
        try:
            text = text.lower().replace(',', '').replace(' ', '')
            multipliers = {
                'tr': 1_000_000, 'triệu': 1_000_000, 'trieu': 1_000_000,
                'k': 1_000, 'ngàn': 1_000, 'nghìn': 1_000,
                'tỉ': 1_000_000_000, 'tỷ': 1_000_000_000
            }
            match = re.search(r'(\d+\.?\d*)', text)
            if match:
                number = float(match.group(1))
                for u, m in multipliers.items():
                    if u in text: return number * m
                return number
        except: pass
        return None

    def analyze_message(self, message: str, sender_name: Optional[str] = None):
        """Hybrid analysis: Regex Fast-path + AI Fallback"""
        if not self.client: return {"data": {}, "metadata": {}}
        
        msg_lower = message.lower()
        if "nghỉ" in msg_lower and len(message) < 50:
             return {
                "data": {"intent": "leave_request", "confidence": 0.95, "metadata": {"customer_name": sender_name}},
                "metadata": {"source": "regex"}
             }

        prompt_template = self._get_prompt("message_analysis")
        try:
            response = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Vietnamese Intent Analyzer. Output JSON only."},
                    {"role": "user", "content": f"Context: {sender_name}\nPrompt: {prompt_template}\nInput: {message}"},
                ],
                response_format={"type": "json_object"},
                temperature=0,
            )
            raw_content = response.choices[0].message.content or "{}"
            data = json.loads(raw_content)
            return {"data": data, "metadata": {"source": "openai"}}
        except Exception as e:
            Log.error(f"[OPENAI] ❌ Message analysis error: {e}")
            return {"data": {}, "metadata": {}}

# Singleton instance
openai_extractor = OpenAIExtractor()
