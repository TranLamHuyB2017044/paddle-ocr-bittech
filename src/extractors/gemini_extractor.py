"""
Gemini Extractor
Helper to extract CCCD data using Google Gemini API with Structured Output (Pydantic)
"""
import os
import json
from typing import Optional
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from src.config import GEMINI_API_KEY
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

class GeminiExtractor:
    def __init__(self):
        if not GEMINI_API_KEY:
            Log.warning("[GEMINI] ⚠️  Warning: GEMINI_API_KEY is not set. Check .env file.")
            self.client = None
        else:
            try:
                # Initialize Google GenAI Client
                self.client = genai.Client(api_key=GEMINI_API_KEY)
                Log.info("[GEMINI] ✅ Gemini Client initialized successfully.")
            except Exception as e:
                Log.error(f"[GEMINI] ❌ Error configuring Gemini Client: {e}")
                self.client = None

    def extract(self, text_lines, doc_type):
        """
        Extract Information using Gemini with Structured Output
        
        Args:
            text_lines: List of OCR text lines
            doc_type: Type of document (enum: idCard, driverLicense, invoice, document)
            
        Returns:
            dict: JSON extracted data or empty dict if failed
        """
        if not self.client:
            Log.error("[GEMINI] ❌ No client available. Check API Key.")
            return {"data": {}, "metadata": {}}

        # Prepare content
        text_block = "\n".join(text_lines)
        
        # Read prompt from file based on doc_type
        # Default prompt directory
        prompt_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts')
        prompt_file = f"{doc_type}.md"
        prompt_path = os.path.join(prompt_dir, prompt_file)

        if not os.path.exists(prompt_path):
             Log.error(f"[GEMINI] ❌ Prompt file not found: {prompt_path}")
             return {"data": {}, "metadata": {}}

        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompt_template = f.read()
            
            # Append input text to the prompt
            prompt = f"{prompt_template}\n\nINPUT DATA:\n{text_block}"
            Log.debug(f"[GEMINI] 📝 Prompt loaded for {doc_type}")
        except Exception as e:
            Log.warning(f"[GEMINI] ⚠️  Could not read prompt file: {e}.")
            return {"data": {}, "metadata": {}}

        # Configure Generation
        response_schema = SCHEMA_MAP.get(doc_type)

        # Generate content with structured output
        Log.info(f"[GEMINI] 🚀 Sending request to Gemini ({doc_type})...")
        try:
            config = types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=response_schema,
                maxOutputTokens = 5000
            )
            
            # Add thinking config only for idCard (optimization)
            if doc_type == "idCard":
                 config.thinking_config = types.ThinkingConfig(thinking_budget=1024) 

            response = self.client.models.generate_content(
                model="gemini-3-flash-preview", 
                contents=prompt,
                config=config,
            )
            
            # Parse and validate response
            data = {}
            if response.parsed:
                 # Convert to dict using by_alias=True to handle 'class' field map
                data = response.parsed.model_dump(mode='json', by_alias=True)
            
            # Fallback text parsing
            if not data and response.text:
                try:
                    import json
                    import re
                    # Robust extraction of JSON block
                    # Find content between first { and last }
                    match = re.search(r'\{.*\}', response.text, re.DOTALL)
                    if match:
                        clean_text = match.group(0)
                        data = json.loads(clean_text)
                    else:
                        # Fallback for simple strip if regex fails (unlikely for JSON object)
                        clean_text = response.text.strip()
                        if clean_text.startswith("```json"):
                            clean_text = clean_text[7:]
                        if clean_text.endswith("```"):
                            clean_text = clean_text[:-3]
                        data = json.loads(clean_text)
                except Exception as e:
                    Log.warning(f"[GEMINI] ⚠️ Check parsed failed, text clean failed: {e}")

            # Extract metadata
            metadata = {}
            if response.usage_metadata:
                metadata = {
                    "prompt_token_count": response.usage_metadata.prompt_token_count,
                    "candidates_token_count": response.usage_metadata.candidates_token_count,
                    "total_token_count": response.usage_metadata.total_token_count,
                }

            if data:
                Log.info(f"[GEMINI] ✅ Extraction successful.")
                return {
                    "data": data,
                    "metadata": metadata
                }
            else:
                Log.error(f"[GEMINI] ❌ No parsed data available.")
                return {"data": {}, "metadata": {}}

        except Exception as e:
            Log.error(f"[GEMINI] ❌ Generation Error: {e}")
            # Raise exception to allow fallback in caller
            raise e

# Global instance
gemini_extractor = GeminiExtractor()
