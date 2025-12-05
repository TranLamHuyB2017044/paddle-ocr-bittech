"""
Gemini Extractor
Helper to extract CCCD data using Google Gemini API with Structured Output (Pydantic)
"""
import os
import json
from typing import Optional
from google import genai
from pydantic import BaseModel, Field
from cccd.config import GEMINI_API_KEY

# Define Pydantic Models matching read_cccd.md
class CCCD(BaseModel):
    fullName: Optional[str] = Field(description="Fullname/Họ và tên")
    idNumber: Optional[str] = Field(description="Số/Number/No")
    dob: Optional[str] = Field(description="Date of birth (YYYY-MM-DD)")
    gender: Optional[str] = Field(description="Gender (Nam/Nữ)")
    nationality: Optional[str] = Field(description="Nationality")
    hometown: Optional[str] = Field(description="Place of origin/Quê quán")
    address: Optional[str] = Field(description="Address/Nơi thường trú")
    expiryDate: Optional[str] = Field(description="Date of expiry")
    dateOfIssue: Optional[str] = Field(description="Date of issue")
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
            return {}

        try:
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
                return {}

            # Generate content with structured output
            print("[GEMINI] 🚀 Sending request to Gemini (Structured)...")
            response = self.client.models.generate_content(
                model="gemini-2.0-flash", 
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": CCCD,
                },
            )
            
            # Parse and validate response
            if response.parsed:
                 # Convert to dict
                data = response.parsed.model_dump(mode='json')
                print(f"[GEMINI] ✅ Extraction successful: {data}")
                return data
            else:
                # Retry or handle raw text if schema failed (fallback mechanism could be added here)
                print(f"[GEMINI] ❌ No parsed data received.")
                return {}

        except Exception as e:
            print(f"[GEMINI] ❌ Extraction failed: {e}")
            return {}

# Global instance
gemini_extractor = GeminiExtractor()
