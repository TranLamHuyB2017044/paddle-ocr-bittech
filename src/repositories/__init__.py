"""
Repositories Compatibility Shim Package
Redirects legacy 'src.repositories.*' imports to 'src.shared.repositories.*'.
"""
import sys
import src.shared.repositories as _shared_repositories

__path__ = _shared_repositories.__path__
sys.modules['src.repositories'] = _shared_repositories

from src.shared.repositories import *  # noqa: F401, F403
