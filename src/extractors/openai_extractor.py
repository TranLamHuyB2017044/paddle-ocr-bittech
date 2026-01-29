"""
OpenAI Extractor
Helper to extract CCCD data using OpenAI API with Structured Output
"""
import os
import json
from typing import Optional
from openai import OpenAI
from src.config import OPENAI_API_KEY
from src.utils.logger import Log
from src.models.schemas import IdCard, DriverLicense, Invoice, Document, VehicleDocument

# Map doc_type string to Pydantic model
SCHEMA_MAP = {
    "idCard": IdCard,
    "driverLicense": DriverLicense,
    "invoice": Invoice,
    "document": Document,
    "vehicleDocuments": VehicleDocument
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

    def extract(self, text_lines, doc_type):
        """
        Extract Information using OpenAI with Structured Output
        
        Args:
            text_lines: List of OCR text lines
            doc_type: Type of document (enum: idCard, driverLicense, invoice, document)
            
        Returns:
            dict: JSON extracted data or empty dict if failed
        """
        if not self.client:
            Log.error("[OPENAI] ❌ No client available. Check API Key.")
            return {"data": {}, "metadata": {}}

        # Prepare content
        text_block = "\n".join(text_lines)
        
        # Read prompt from file based on doc_type
        prompt_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts')
        prompt_file = f"{doc_type}.md"
        prompt_path = os.path.join(prompt_dir, prompt_file)

        if not os.path.exists(prompt_path):
             Log.error(f"[OPENAI] ❌ Prompt file not found: {prompt_path}")
             return {"data": {}, "metadata": {}}

        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompt_template = f.read()
            
            # Append input text to the prompt
            prompt = f"{prompt_template}\n\nINPUT DATA:\n{text_block}"
        except Exception as e:
            Log.warning(f"[OPENAI] ⚠️ Could not read prompt file: {e}.")
            return {"data": {}, "metadata": {}}

        # Configure Response Format
        response_schema = SCHEMA_MAP.get(doc_type)

        Log.info(f"[OPENAI] 🚀 Sending request to OpenAI (gpt-4o-mini, {doc_type})...")
        try:
            # Use gpt-4o-mini for speed and cost effectiveness
            # Use the newer responses.parse or beta.chat.completions.parse API
            completion = self.client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are a specialized OCR data extractor. Extract information accurately from the provided text according to the specific format requested."},
                    {"role": "user", "content": prompt},
                ],
                response_format=response_schema,
                temperature=0.7
            )
            
            # Extract result
            message = completion.choices[0].message
            if message.parsed:
                data = message.parsed.model_dump(mode='json', by_alias=True)
            else:
                Log.warning("[OPENAI] ⚠️ No parsed data in response.")
                data = {}

            # Extract metadata
            metadata = {
                "prompt_tokens": completion.usage.prompt_tokens,
                "completion_tokens": completion.usage.completion_tokens,
                "total_tokens": completion.usage.total_tokens,
            }

            if data:
                Log.info(f"[OPENAI] ✅ Extraction successful. Tokens: T={metadata.get('total_tokens', 0)}")
                # For consistency with other parts of the system, we still return output_text logic if needed
                # But here we focus on .parsed
                return {
                    "data": data,
                    "metadata": metadata
                }
            else:
                Log.error(f"[OPENAI] ❌ Extraction failed to produce data.")
                return {"data": {}, "metadata": metadata}

        except Exception as e:
            Log.error(f"[OPENAI] ❌ OpenAI Error: {e}")
            raise e

# Global instance
openai_extractor = OpenAIExtractor()
