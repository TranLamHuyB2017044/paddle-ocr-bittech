"""
RAG Compatibility Shim Package
Redirects legacy 'src.rag.*' imports to 'src.modules.rag.*'.
"""
import sys
import src.modules.rag as _rag

__path__ = _rag.__path__
sys.modules['src.rag'] = _rag

from src.modules.rag import *  # noqa: F401, F403
