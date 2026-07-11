"""Compatibility alias for Platform database pool management."""
import sys
from importlib import import_module

_implementation = import_module("novelwiki.platform.database.pool")
sys.modules[__name__] = _implementation
