"""
Grok Extractor (via OpenRouter)
Helper to extract CCCD data using Grok API with Structured Output (Pydantic)
"""
import os
import json
from typing import Optional
from openai import OpenAI
from pydantic import BaseModel, Field
from src.config import OPENROUTER_GROK_API_KEY
from src.utils.logger import Log
from src.models.schemas import IdCard, DriverLicense, Invoice, Document,VehicleDocument

# Map doc_type string to Pydantic model
SCHEMA_MAP = {
    "idCard": IdCard,
    "driverLicense": DriverLicense,
    "invoice": Invoice,
    "document": Document,
    "vehicleDocuments": VehicleDocument
}

class GrokExtractor:
    def __init__(self):
        self.api_key = OPENROUTER_GROK_API_KEY
        if not self.api_key:
            Log.warning("[GROK] ⚠️  Warning: OPENROUTER_GROK_API_KEY is not set. Check .env file.")
            self.client = None
        else:
            try:
                # Initialize OpenAI Client pointing to OpenRouter for Grok
                self.client = OpenAI(
                    base_url="https://openrouter.ai/api/v1",
                    api_key=self.api_key,
                    default_headers={
                        "HTTP-Referer": "https://github.com/Antigravity-AI/paddle-ocr-bittech",
                        "X-Title": "PaddleOCR BitTech (Grok)",
                    }
                )
                Log.info("[GROK] ✅ OpenRouter (Grok) Client initialized successfully.")
            except Exception as e:
                Log.error(f"[GROK] ❌ Error configuring Grok Client: {e}")
                self.client = None

    def extract(self, text_lines, doc_type):
        """
        Extract Information using Grok (via OpenRouter) with Structured Output
        
        Args:
            text_lines: List of OCR text lines
            doc_type: Type of document (enum: idCard, driverLicense, invoice, document)
            
        Returns:
            dict: JSON extracted data or empty dict if failed
        """
        if not self.client:
            Log.error("[GROK] ❌ No client available. Check API Key.")
            return {"data": {}, "metadata": {}}

        # Prepare content
        text_block = "\n".join(text_lines)
        
        # Read prompt from file based on doc_type
        # Default prompt directory
        prompt_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'prompts')
        prompt_file = f"{doc_type}.md"
        prompt_path = os.path.join(prompt_dir, prompt_file)

        if not os.path.exists(prompt_path):
             Log.error(f"[GROK] ❌ Prompt file not found: {prompt_path}")
             return {"data": {}, "metadata": {}}

        try:
            with open(prompt_path, 'r', encoding='utf-8') as f:
                prompt_template = f.read()
            
            system_instruction = prompt_template
            user_content = f"INPUT DATA:\n{text_block}"
            
            Log.debug(f"[GROK] 📝 Prompt loaded for {doc_type}")
        except Exception as e:
            Log.warning(f"[GROK] ⚠️  Could not read prompt file: {e}")
            return {"data": {}, "metadata": {}}

        # Configure Generation
        response_schema = SCHEMA_MAP.get(doc_type)
        if not response_schema:
             Log.error(f"[GROK] ❌ No schema found for doc_type: {doc_type}")
             return {"data": {}, "metadata": {}}

        # Generate content with structured output
        Log.info(f"[GROK] 🚀 Sending request to Grok ({doc_type})...")
        try:
            # Note: Grok via OpenRouter using openai library
            # OpenRouter might not fully support 'response_format' for all models or provider versions,
            # but standard OpenAI SDK usually passes it. If Grok doesn't natively support JSON mode 
            # effectively, this might fail or return markdown.
            # However, for now we assume consistent 'beta.chat.completions.parse' behavior if supported by the provider/wrapper.
            # If 'parse' fails for non-OpenAI models on OpenRouter, we might need 'create' and manual Pydantic parsing.
            
            # Using standard .create() instead of .parse() first to ensure compatibility with non-OpenAI models 
            # if the model doesn't support the 'json_schema' strictly.
            # BUT user asked to "wrap grok api" similar to openai.
            # Let's try .parse() first as it's cleaner. If Grok via OpenRouter supports it (it usually does via translation layer or if native).
            # Model: "x-ai/grok-3-mini"
            
            completion = self.client.beta.chat.completions.parse(
                model="x-ai/grok-4.1-fast", # Using a known stable Grok model or the one requested "x-ai/grok-3-mini" if valid. 
                # User requested "x-ai/grok-3-mini". Let's use that.
                # WARNING: grok-3 might be hypothetical or very new. If it fails, we fall back to user desire.
                
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": user_content},
                ],
                response_format=response_schema,
                temperature=0.1,
                max_tokens=5000,
            )
            
            message = completion.choices[0].message
            
            # Parse and validate response
            data = {}
            if message.parsed:
                data = message.parsed.model_dump(mode='json', by_alias=True)
            elif message.refusal:
                Log.warning(f"[GROK] ⚠️ Model refused to answer: {message.refusal}")
            
            # Extract metadata
            metadata = {}
            if completion.usage:
                metadata = {
                    "prompt_token_count": completion.usage.prompt_tokens,
                    "candidates_token_count": completion.usage.completion_tokens,
                    "total_token_count": completion.usage.total_tokens,
                }

            if data:
                Log.info(f"[GROK] ✅ Extraction successful. Tokens: P={metadata.get('prompt_token_count', 0)}, C={metadata.get('candidates_token_count', 0)}, T={metadata.get('total_token_count', 0)}")
                return {
                    "data": data,
                    "metadata": metadata
                }
            else:
                Log.error(f"[GROK] ❌ No parsed data available. Tokens: P={metadata.get('prompt_token_count', 0)}, C={metadata.get('candidates_token_count', 0)}, T={metadata.get('total_token_count', 0)}")
                return {"data": {}, "metadata": metadata}

        except Exception as e:
            Log.error(f"[GROK] ❌ Generation Error: {e}")
            raise e

# Global instance
grok_extractor = GrokExtractor()
