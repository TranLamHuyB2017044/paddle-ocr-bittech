import logging
import sys

class Log:
    _logger = None

    @classmethod
    def _get_logger(cls):
        if cls._logger:
            return cls._logger
            
        logger = logging.getLogger("CCCD_OCR")
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
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
