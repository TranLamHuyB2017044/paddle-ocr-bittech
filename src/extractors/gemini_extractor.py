import os
import json
import base64
import re
import PIL.Image
from typing import Optional, List, Union
from google import genai
from google.genai import types

from src.config import GEMINI_API_KEY, GEMINI_MODEL
from src.utils.logger import Log
from src.models.schemas import IdCard, DriverLicense, Invoice, Document, VehicleDocument, RestaurantMenu, MessageAnalysis
from src.extractors.openai_extractor import openai_extractor

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

class GeminiExtractor:
    def __init__(self):
        self.is_configured = False
        self.client = None
        if not GEMINI_API_KEY:
            Log.warning("[GEMINI] ⚠️ Warning: GEMINI_API_KEY is not set.")
        else:
            try:
                self.client = genai.Client(api_key=GEMINI_API_KEY)
                self.model_name = GEMINI_MODEL  # Nhanh và tối ưu
                self.is_configured = True
                Log.info(f"[GEMINI] ✅ Gemini Client initialized successfully using new google-genai SDK. Model: {self.model_name}")
            except Exception as e:
                Log.error(f"[GEMINI] ❌ Error configuring Gemini Client: {e}")

    def _get_prompt(self, doc_type):
        """Đọc Prompt từ file .md trong thư mục prompts"""
        prompt_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts')
        prompt_path = os.path.join(prompt_dir, f"{doc_type}.md")

        if not os.path.exists(prompt_path):
             Log.error(f"[GEMINI] ❌ Prompt file not found: {prompt_path}")
             return None
             
        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            Log.warning(f"[GEMINI] ⚠️ Could not read prompt file: {e}")
            return None

    def extract(self, text_lines: List[str], doc_type: str):
        """Xử lý trích xuất dựa trên Text OCR"""
        if not self.is_configured or self.client is None: 
            return openai_extractor.extract(text_lines, doc_type)

        text_block = "\n".join(text_lines).strip()
        
        if not text_block or len(text_block) < 3:
            Log.warning(f"[GEMINI] ⚠️ Input too short for {doc_type}. Skipping...")
            return {"data": {}, "metadata": {"status": "empty_input"}}

        prompt_template = self._get_prompt(doc_type)
        if not prompt_template: 
            return {"data": {}, "metadata": {"error": "prompt_not_found"}}
        
        prompt = f"{prompt_template}\n\nLưu ý: Chỉ trả về JSON thuần tuý, không kèm markdown (như ```json).\n\nINPUT DATA (OCR TEXT):\n{text_block}"
        
        Log.info(f"[GEMINI] 🚀 Key Extraction for {doc_type}...")
        try:
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
            )
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config
            )
            return self._process_completion(response.text, doc_type)
        except Exception as e:
            Log.error(f"[GEMINI] ❌ Gemini Error (Rate limit/Quota?): {e}. Fallback to OpenAI...")
            return openai_extractor.extract(text_lines, doc_type)

    def extract_with_vision(self, image_paths: Union[str, List[str]], doc_type: str):
        """Vision-based extraction (hỗ trợ 1 hoặc nhiều ảnh) - Ưu tiên Gemini, Fallback OpenAI"""
        if isinstance(image_paths, str):
            image_paths = [image_paths]
            
        if not self.is_configured or self.client is None:
            Log.warning("[GEMINI] ⚠️ Gemini is not configured, fallback directly to OpenAI.")
            return openai_extractor.extract_with_vision(image_paths, doc_type)

        images = []
        for p in image_paths:
            try:
                images.append(PIL.Image.open(p))
            except Exception as e:
                Log.error(f"[GEMINI-VLM] ❌ Could not open image {p}: {e}")

        if not images:
            return {"data": {}, "metadata": {"error": "no_valid_images"}}

        prompt_template = self._get_prompt(doc_type)
        if not prompt_template: 
            return {"data": {}, "metadata": {"error": "prompt_not_found"}}

        prompt = f"{prompt_template}\n\nLưu ý: Bạn là chuyên gia trích xuất tài liệu.\nHãy trích xuất dữ liệu từ các hình ảnh đính kèm một cách chính xác.\nChỉ trả về định dạng JSON thuần tuý, tuyệt đối không kèm block markdown (```json ... ```)."

        Log.info(f"[GEMINI-VLM] 👁️ Vision Extraction for {doc_type} with {len(images)} images...")
        try:
            config = types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.0,
            )
            contents = [prompt] + images
            
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config
            )
            return self._process_completion(response.text, doc_type)
        except Exception as e:
            Log.error(f"[GEMINI-VLM] ❌ Gemini Error: {e}. Limit exceeded or error occurred. Auto fallback to OpenAI!")
            # Fallback to OpenAI (đã hỗ trợ list ảnh)
            return openai_extractor.extract_with_vision(image_paths, doc_type)

    def _process_completion(self, response_text: str, doc_type: str):
        """Hậu xử lý kết quả: Chuyển JSON string thành dict và chuyển đổi tiền tệ"""
        try:
            # Làm sạch chuỗi json nếu model vô tình nhét markdown
            clean_text = response_text.strip()
            if clean_text.startswith("```json"):
                clean_text = clean_text[7:]
            if clean_text.startswith("```"):
                clean_text = clean_text[3:]
            if clean_text.endswith("```"):
                clean_text = clean_text[:-3]
            
            data = json.loads(clean_text.strip())
        except json.JSONDecodeError as e:
            Log.error(f"[GEMINI] ❌ JSON Decode Error: {e}\nResponse text: {response_text}")
            data = {}

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
            "source": "gemini",
            "model": self.model_name
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

# Singleton instance
gemini_extractor = GeminiExtractor()
