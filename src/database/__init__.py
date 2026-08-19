"""
Database Compatibility Shim Package
Redirects legacy 'src.database.*' imports to 'src.core.database.*'.
"""
import sys
import src.core.database as _core_database

__path__ = _core_database.__path__
sys.modules['src.database'] = _core_database

from src.core.database import *  # noqa: F401, F403
