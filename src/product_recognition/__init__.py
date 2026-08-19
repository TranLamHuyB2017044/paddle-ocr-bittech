"""
Product Recognition Compatibility Shim Package
Redirects legacy 'src.product_recognition.*' imports to 'src.modules.product_recognition.*'.
"""
import sys
import src.modules.product_recognition as _prod_rec

__path__ = _prod_rec.__path__
sys.modules['src.product_recognition'] = _prod_rec

from src.modules.product_recognition import *  # noqa: F401, F403
