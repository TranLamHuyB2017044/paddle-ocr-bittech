import logging
import os
import sys

class Log:
    _logger = None

    @classmethod
    def _get_logger(cls):
        if cls._logger:
            return cls._logger
            
        logger = logging.getLogger("CCCD_OCR")
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()
        logger.setLevel(getattr(logging, log_level, logging.INFO))
        
        if not logger.handlers:
            if hasattr(sys.stdout, "reconfigure"):
                try:
                    sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
                except Exception:
                    pass
            handler = logging.StreamHandler(sys.stdout)
            # Simple format, similar to what user had but with timestamp
            formatter = logging.Formatter(
                '%(asctime)s | %(levelname)s | %(message)s', 
                datefmt='%Y-%m-%d %H:%M:%S'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        cls._logger = logger
        return cls._logger

    @classmethod
    def info(cls, msg):
        cls._get_logger().info(msg)

    @classmethod
    def error(cls, msg):
        cls._get_logger().error(msg)
    
    @classmethod
    def warning(cls, msg):
        cls._get_logger().warning(msg)
        
    @classmethod
    def debug(cls, msg):
        cls._get_logger().debug(msg)
