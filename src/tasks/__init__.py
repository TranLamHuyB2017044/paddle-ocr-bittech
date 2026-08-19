"""
Tasks Compatibility Shim Package
Redirects legacy 'src.tasks.*' imports to 'src.shared.tasks.*'.
"""
import sys
import src.shared.tasks as _shared_tasks

__path__ = _shared_tasks.__path__
sys.modules['src.tasks'] = _shared_tasks

from src.shared.tasks import *  # noqa: F401, F403
