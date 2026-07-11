"""Compatibility alias for Platform Observability."""
import sys
from importlib import import_module

_implementation = import_module("novelwiki.platform.observability.audit")
sys.modules[__name__] = _implementation
