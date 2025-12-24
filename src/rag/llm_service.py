from src.extractors.grok_extractor import grok_extractor
from src.extractors.gemini_extractor import gemini_extractor
from src.utils.logger import Log

class LLMService:
    def chat(self, prompt, system_instruction="You are a helpful assistant.", provider="auto"):
        """
        Generic chat method that tries Grok then Gemini.
        Returns: (answer_text, provider_name)
        """
        if provider == "gemini":
            return self._chat_gemini(prompt, system_instruction), "gemini"
        elif provider == "grok":
            return self._chat_grok(prompt, system_instruction), "grok"
        
        # Auto: Try Grok first, then Gemini
        try:
            Log.info("[LLM] 🤖 Attempting chat with Grok...")
            return self._chat_grok(prompt, system_instruction), "grok"
        except Exception as e:
            Log.warning(f"[LLM] ⚠️ Grok failed, falling back to Gemini: {e}")
            return self._chat_gemini(prompt, system_instruction), "gemini"

    def _chat_grok(self, prompt, system_instruction):
        if not grok_extractor.client:
            raise Exception("Grok client not initialized")
        
        Log.debug(f"[LLM-Grok] Sending prompt: {prompt[:100]}...")
        completion = grok_extractor.client.chat.completions.create(
            model="x-ai/grok-4.1-fast", # or another stable model
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            temperature=0.7,
        )
        answer = completion.choices[0].message.content
        Log.info(f"[LLM-Grok] ✅ Received answer ({len(answer)} chars)")
        return answer

    def _chat_gemini(self, prompt, system_instruction):
        # We assume gemini_extractor has a client
        if not gemini_extractor.client:
             raise Exception("Gemini client not initialized")
        
        Log.debug(f"[LLM-Gemini] Sending prompt: {prompt[:100]}...")
        response = gemini_extractor.client.models.generate_content(
            model='gemini-3-flash-preview',
            contents=prompt,
            config={
                'system_instruction': system_instruction,
                'temperature': 0.7
            }
        )
        answer = response.text
        Log.info(f"[LLM-Gemini] ✅ Received answer ({len(answer)} chars)")
        return answer

llm_service = LLMService()
