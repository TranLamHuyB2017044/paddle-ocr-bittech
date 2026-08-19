"""
Utils Compatibility Shim Package
Redirects legacy 'src.utils.*' imports to 'src.shared.utils.*'.
"""
import sys
import src.shared.utils as _shared_utils

__path__ = _shared_utils.__path__
sys.modules['src.utils'] = _shared_utils

from src.shared.utils import *  # noqa: F401, F403
