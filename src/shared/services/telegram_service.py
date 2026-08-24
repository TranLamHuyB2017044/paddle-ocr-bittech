import requests
from src.shared.utils.logger import Log


def send_telegram_message(bot_token: str, chat_id: str, message: str) -> bool:
    """
    Gửi tin nhắn tới Telegram
    
    Args:
        bot_token: Token của Telegram Bot
        chat_id: Chat ID của người nhận
        message: Nội dung tin nhắn
    
    Returns:
        True nếu gửi thành công, False nếu thất bại
    """
    if not bot_token or not chat_id or not message:
        Log.warning("[Telegram] Thiếu thông tin cần thiết để gửi tin nhắn")
        return False
    
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "Markdown"
        }
        
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        
        Log.info(f"[Telegram] Đã gửi tin nhắn thành công tới chat ID {chat_id}")
        return True
    except requests.exceptions.RequestException as e:
        Log.error(f"[Telegram] Lỗi khi gửi tin nhắn: {str(e)}")
        return False


def format_customer_question_notification(question: str, chatbot_name: str = "Chatbot") -> str:
    """
    Định dạng tin nhắn thông báo câu hỏi khách hàng
    
    Args:
        question: Câu hỏi của khách hàng
        chatbot_name: Tên chatbot
    
    Returns:
        Tin nhắn đã được định dạng
    """
    from datetime import datetime
    
    now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    
    return (
        f"🔔 *CÂU HỎI MỚI TỪ KHÁCH HÀNG*\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🤖 Chatbot: {chatbot_name}\n"
        f"⏰ Thời gian: {now}\n\n"
        f"❓ Câu hỏi:\n"
        f"```\n{question}\n```\n\n"
        f"👉 Vui lòng phản hồi khách hàng sớm nhất!"
    )
