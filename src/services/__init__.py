"""
Services Compatibility Shim Package
Redirects legacy 'src.services.*' imports to 'src.shared.services.*'.
"""
import sys
import src.shared.services as _shared_services

__path__ = _shared_services.__path__
sys.modules['src.services'] = _shared_services

from src.shared.services import *  # noqa: F401, F403
