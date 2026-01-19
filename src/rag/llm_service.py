from src.extractors.openai_extractor import openai_extractor
from src.utils.logger import Log

class LLMService:
    def chat(self, prompt, system_instruction="You are a helpful assistant.", provider="auto"):
        """
        Generic chat method that tries OpenAI then Gemini.
        Returns: (answer_text, provider_name)
        """
        if provider == "openai":
            try:
                return self._chat_openai(prompt, system_instruction), "openai"
            except Exception as e:
                Log.error(f"[LLM] ⚠️ OpenAI failed: {e}")
                raise Exception("Hệ thống đang lỗi vui lòng thử lại sau")
        
        # Auto: Try OpenAI first
        try:
            Log.info("[LLM] 🤖 Attempting chat with OpenAI...")
            return self._chat_openai(prompt, system_instruction), "openai"
        except Exception as e:
            Log.error(f"[LLM] ⚠️ OpenAI failed: {e}")
            # Trả lỗi cụ thể cho FE
            raise Exception("Hệ thống đang lỗi vui lòng thử lại sau")

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
        answer = completion.choices[0].message.content
        Log.info(f"[LLM-OpenAI] ✅ Received answer ({len(answer)} chars)")
        return answer

llm_service = LLMService()
