from src.shared.extractors.openai_extractor import openai_extractor
from src.shared.extractors.gemini_extractor import gemini_extractor
from src.shared.utils.logger import Log
from google.genai import types

class LLMService:
    def chat(self, prompt, system_instruction="You are a helpful assistant.", provider="openai"):
        """
        Chat method chỉ sử dụng OpenAI (tạm thời bỏ qua Gemini).
        Nếu OpenAI lỗi, ném lỗi chi tiết rõ ràng để debug/kiểm tra.
        Returns: (answer_text, provider_name)
        """
        try:
            Log.info("[LLM] 🤖 Chatting with OpenAI...")
            return self._chat_openai(prompt, system_instruction), "openai"
        except Exception as e:
            err_msg = str(e)
            Log.error(f"[LLM] ❌ OpenAI chat failed: {err_msg}")
            raise Exception(f"Lỗi OpenAI: {err_msg}")

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

    def generate_title(self, raw_text: str, fallback_filename: str = "Tài liệu không tên") -> str:
        """
        Sinh tiêu đề ngắn gọn (< 10 từ) từ nội dung văn bản (bằng Gemini Flash / OpenAI).
        Nếu lỗi hoặc text quá ngắn, trả về fallback_filename.
        """
        if not raw_text or len(raw_text.strip()) < 10:
            return fallback_filename

        sample_text = raw_text.strip()[:1500]
        prompt = (
            "Dựa vào đoạn trích nội dung văn bản sau, hãy đặt một tiêu đề ngắn gọn (dưới 10 từ) "
            "thể hiện chính xác nội dung/chủ đề hoặc loại tài liệu (ví dụ: 'Hóa đơn tiền điện tháng 8/2026', "
            "'Hợp đồng lao động Nguyễn Văn A', 'Báo cáo tài chính Quý 2/2026', 'Quy chế bảo mật thông tin').\n"
            "Yêu cầu:\n"
            "- Chỉ trả về DUY NHẤT chuỗi tiêu đề.\n"
            "- KHÔNG kèm dấu ngoặc kép, dấu gạch đầu dòng, dấu chấm câu ở cuối hoặc từ giải thích thừa.\n"
            "- Giữ nguyên ngôn ngữ chính của tài liệu (ưu tiên tiếng Việt nếu tài liệu bằng tiếng Việt).\n"
            "- Tối đa 10 từ.\n\n"
            f"Nội dung văn bản:\n{sample_text}"
        )
        system_instruction = "Bạn là chuyên gia trích xuất và đặt tiêu đề tài liệu ngắn gọn, súc tích."
        
        try:
            import re
            # Mặc định dùng OpenAI, fallback sang Gemini nếu lỗi/không cấu hình
            answer = ""
            if openai_extractor.client:
                try:
                    answer = self._chat_openai(prompt, system_instruction)
                except Exception as oe:
                    Log.warning(f"[LLM-Title] ⚠️ OpenAI lỗi: {oe}. Đang thử fallback sang Gemini...")
                    if gemini_extractor.is_configured and gemini_extractor.client:
                        answer = self._chat_gemini(prompt, system_instruction)
                    else:
                        raise oe
            elif gemini_extractor.is_configured and gemini_extractor.client:
                answer = self._chat_gemini(prompt, system_instruction)
            
            clean_title = answer.strip().strip('"\'`\n\r').replace('\n', ' ')
            clean_title = re.sub(r'^[#*\-\s]+', '', clean_title)
            clean_title = re.sub(r'[*_`]', '', clean_title).strip()
            
            if clean_title and len(clean_title) <= 120:
                Log.info(f"[LLM-Title] ✅ Generated title: '{clean_title}' (fallback: '{fallback_filename}')")
                return clean_title
        except Exception as e:
            Log.warning(f"[LLM-Title] ⚠️ Không thể sinh tiêu đề thông minh: {e}. Sử dụng fallback '{fallback_filename}'.")
        
        return fallback_filename

llm_service = LLMService()
