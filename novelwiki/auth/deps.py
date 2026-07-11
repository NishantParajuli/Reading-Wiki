"""Compatibility alias for Identity's FastAPI dependencies."""
import sys
from importlib import import_module

_implementation = import_module(
    "novelwiki.modules.identity.adapters.inbound.dependencies"
)
sys.modules[__name__] = _implementation
