"""
Models Compatibility Shim Package
Redirects legacy 'src.models.*' imports to 'src.shared.models.*'.
"""
import sys
import src.shared.models as _shared_models

__path__ = _shared_models.__path__
sys.modules['src.models'] = _shared_models

from src.shared.models import *  # noqa: F401, F403
