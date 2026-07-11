import sys
from importlib import import_module
_implementation = import_module("novelwiki.modules.identity.adapters.outbound.email")
sys.modules[__name__] = _implementation
