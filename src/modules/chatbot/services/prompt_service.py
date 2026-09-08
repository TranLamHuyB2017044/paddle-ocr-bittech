import os
from src.shared.utils.logger import Log
from src.modules.chatbot.models.chatbot import ChatbotDomain

def get_chatbot_prompt(domain: str | None = None) -> str:
    """
    Đọc System Prompt từ file .md tương ứng trong thư mục src/shared/prompts/chatbot/
    """
    try:
        services_dir = os.path.dirname(os.path.abspath(__file__))
        src_dir = os.path.dirname(os.path.dirname(os.path.dirname(services_dir)))
        prompt_dir = os.path.join(src_dir, 'shared', 'prompts', 'chatbot')
        
        normalized_domain = domain.lower().strip() if domain else ChatbotDomain.ECOMMERCE.value
        prompt_path = os.path.join(prompt_dir, f"{normalized_domain}.md")
        
        if not os.path.exists(prompt_path):
            prompt_path = os.path.join(prompt_dir, "general.md")
            if not os.path.exists(prompt_path):
                return "Bạn là trợ lý chatbot hỗ trợ thông tin chuyên nghiệp."
                
        with open(prompt_path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception as e:
        Log.warning(f"[ChatbotPrompt] ⚠️ Could not read prompt for domain '{domain}': {e}")
        return "Bạn là trợ lý chatbot hỗ trợ khách hàng chuyên nghiệp."
