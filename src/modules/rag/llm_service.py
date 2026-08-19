from src.shared.extractors.openai_extractor import openai_extractor
from src.shared.extractors.gemini_extractor import gemini_extractor
from src.shared.utils.logger import Log
from google.genai import types

class LLMService:
    def chat(self, prompt, system_instruction="You are a helpful assistant.", provider="auto"):
        """
        Generic chat method that prioritizes Gemini, falls back to OpenAI.
        Returns: (answer_text, provider_name)
        """
        if provider == "gemini":
            try:
                return self._chat_gemini(prompt, system_instruction), "gemini"
            except Exception as e:
                Log.error(f"[LLM] ⚠️ Gemini failed: {e}")
                raise Exception("Hệ thống đã hết quota, vui lòng thử lại sau")
        
        if provider == "openai":
            try:
                return self._chat_openai(prompt, system_instruction), "openai"
            except Exception as e:
                Log.error(f"[LLM] ⚠️ OpenAI failed: {e}")
                raise Exception("Hệ thống đã hết quota, vui lòng thử lại sau")
        
        # Auto: Try Gemini first, fallback to OpenAI
        try:
            Log.info("[LLM] 🤖 Attempting chat with Gemini...")
            return self._chat_gemini(prompt, system_instruction), "gemini"
        except Exception as e:
            Log.error(f"[LLM] ⚠️ Gemini failed: {e}. Falling back to OpenAI...")
            try:
                Log.info("[LLM] 🤖 Attempting chat with OpenAI...")
                return self._chat_openai(prompt, system_instruction), "openai"
            except Exception as e2:
                Log.error(f"[LLM] ⚠️ OpenAI failed: {e2}")
                # Both failed, throw quota exceed error in Vietnamese
                raise Exception("Hệ thống đã hết quota, vui lòng thử lại sau")

    def _chat_gemini(self, prompt, system_instruction):
        if not gemini_extractor.is_configured or gemini_extractor.client is None:
            raise Exception("Gemini client not initialized")
        
        Log.debug(f"[LLM-Gemini] Sending prompt: {prompt[:100]}...")
        config = types.GenerateContentConfig(
            temperature=0.7
        )
        full_prompt = f"{system_instruction}\n\n{prompt}"
        response = gemini_extractor.client.models.generate_content(
            model=gemini_extractor.model_name,
            contents=full_prompt,
            config=config
        )
        answer = response.text or ""
        Log.info(f"[LLM-Gemini] ✅ Received answer ({len(answer)} chars)")
        return answer

    def _chat_openai(self, prompt, system_instruction):
        if not openai_extractor.client:
            raise Exception("OpenAI client not initialized")
        
        Log.debug(f"[LLM-OpenAI] Sending prompt: {prompt[:100]}...")
        # Use .create() for general text chat, not .parse() without a schema
        completion = openai_extractor.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7
        )
        answer = completion.choices[0].message.content or ""
        Log.info(f"[LLM-OpenAI] ✅ Received answer ({len(answer)} chars)")
        return answer

llm_service = LLMService()
