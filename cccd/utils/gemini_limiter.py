
import time
from datetime import datetime, timedelta

class GeminiRateLimiter:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(GeminiRateLimiter, cls).__new__(cls)
            cls._instance.blocked_until = None
            cls._instance.buffer_time = 0  # Seconds to wait
        return cls._instance

    def is_blocked(self):
        """Check if Gemini is currently in cooldown"""
        if self.blocked_until and datetime.now() < self.blocked_until:
            return True
        return False

    def get_remaining_time(self):
        if not self.blocked_until:
            return 0
        remaining = (self.blocked_until - datetime.now()).total_seconds()
        return max(0, remaining)

    def record_error(self, error):
        """
        Record an error and set cooldown if necessary.
        
        Args:
            error: The exception object or error code/message
        """
        error_str = str(error).lower()
        
        # 429 Too Many Requests
        if "429" in error_str or "quota" in error_str or "too many requests" in error_str:
            # Cooldown 5 minutes for quota issues
            self.blocked_until = datetime.now() + timedelta(minutes=5)
            print(f"[LIMITER] 🛑 Detected 429/Quota. Gemini blocked until {self.blocked_until.strftime('%H:%M:%S')}")
            
        # Timeout
        elif "timeout" in error_str or "deadline" in error_str:
            # Short cooldown 1 minute for timeouts
            self.blocked_until = datetime.now() + timedelta(minutes=1)
            print(f"[LIMITER] ⏰ Detected Timeout. Gemini blocked until {self.blocked_until.strftime('%H:%M:%S')}")
            
        else:
            # 400 or other errors -> No cooldown
            print(f"[LIMITER] ⚠️ Other error ({error_str}). No cooldown.")
            self.blocked_until = None

gemini_limiter = GeminiRateLimiter()
