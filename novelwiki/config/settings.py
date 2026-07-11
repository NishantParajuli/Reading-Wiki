"""Compatibility alias for Platform configuration."""
import sys
from importlib import import_module

_implementation = import_module("novelwiki.platform.config.settings")
sys.modules[__name__] = _implementation
