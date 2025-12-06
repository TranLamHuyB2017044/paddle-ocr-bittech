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
from cccd.config import GEMINI_API_KEY

# Define Pydantic Models matching read_cccd.md
class CCCD(BaseModel):
    fullName: Optional[str] = Field(description="Fullname/Họ và tên")
    idNumber: Optional[str] = Field(description="Số/Number/No")
    dob: Optional[str] = Field(description="Date of birth (DD-MM-YYYY)")
    gender: Optional[str] = Field(description="Gender (Nam/Nữ)")
    nationality: Optional[str] = Field(description="Nationality")
    hometown: Optional[str] = Field(description="Place of origin/Quê quán")
    address: Optional[str] = Field(description="Address/Nơi thường trú")
    expiryDate: Optional[str] = Field(description="Date of expiry (DD-MM-YYYY)")
    dateOfIssue: Optional[str] = Field(description="Date of issue (DD-MM-YYYY)")
    placeOfIssue: Optional[str] = Field(description="Place of issue")
    info_type: Optional[str] = Field(description="Type of document (CCCD, GPLX, HC...)")

class GeminiExtractor:
    def __init__(self):
        if not GEMINI_API_KEY:
            print("[GEMINI] ⚠️  Warning: GEMINI_API_KEY is not set. Check .env file.")
            self.client = None
        else:
            try:
                # Initialize Google GenAI Client
                self.client = genai.Client(api_key=GEMINI_API_KEY)
                print("[GEMINI] ✅ Gemini Client initialized successfully.")
            except Exception as e:
                print(f"[GEMINI] ❌ Error configuring Gemini Client: {e}")
                self.client = None

    def extract(self, text_lines):
        """
        Extract Information using Gemini with Structured Output
        
        Args:
            text_lines: List of OCR text lines
            
        Returns:
            dict: JSON extracted data or empty dict if failed
        """
        if not self.client:
            print("[GEMINI] ❌ No client available. Check API Key.")
            return {"data": {}, "metadata": {}}

        # Prepare content
        text_block = "\n".join(text_lines)
        
        # Read prompt from file
        prompt_file_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'read_cccd.md')
        try:
            with open(prompt_file_path, 'r', encoding='utf-8') as f:
                prompt_template = f.read()
            
            # Append input text to the prompt since the file might not have a placeholder
            prompt = f"{prompt_template}\n\nINPUT DATA:\n{text_block}"
            print("[GEMINI] 📝 Prompt:\n", prompt)
        except Exception as e:
            print(f"[GEMINI] ⚠️  Could not read prompt file: {e}. Using fallback.")
            return {"data": {}, "metadata": {}}

        # Generate content with structured output
        print("[GEMINI] 🚀 Sending request to Gemini (Structured)...")
        response = self.client.models.generate_content(
            model="gemini-2.0-flash", 
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=CCCD,
                maxOutputTokens = 2048,
                thinkingConfig = types.ThinkingConfig(
                    thinkingBudget = 0,
                )
            ),
        )
        
        # Parse and validate response
        if response.parsed:
             # Convert to dict
            data = response.parsed.model_dump(mode='json')
            # Extract metadata
            metadata = {}
            if response.usage_metadata:
                metadata = {
                    "prompt_token_count": response.usage_metadata.prompt_token_count,
                    "candidates_token_count": response.usage_metadata.candidates_token_count,
                    "total_token_count": response.usage_metadata.total_token_count,
                }

            print(f"[GEMINI] ✅ Extraction successful: {data}")
            return {
                "data": data,
                "metadata": metadata
            }
        else:
            # Retry or handle raw text if schema failed (fallback mechanism could be added here)
            print(f"[GEMINI] ❌ No parsed data received.")
            return {"data": {}, "metadata": {}}

# Global instance
gemini_extractor = GeminiExtractor()
