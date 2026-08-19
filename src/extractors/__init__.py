"""
Extractors Compatibility Shim Package
Redirects legacy 'src.extractors.*' imports to 'src.shared.extractors.*'.
"""
import sys
import src.shared.extractors as _shared_extractors

__path__ = _shared_extractors.__path__
sys.modules['src.extractors'] = _shared_extractors

from src.shared.extractors import *  # noqa: F401, F403
