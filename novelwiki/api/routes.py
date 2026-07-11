"""Compatibility alias for direct imports of historical route callables.

The legacy aggregate router is not registered by the application composition root.
"""
import sys
from importlib import import_module

_implementation = import_module("novelwiki.legacy.routes")
sys.modules[__name__] = _implementation
