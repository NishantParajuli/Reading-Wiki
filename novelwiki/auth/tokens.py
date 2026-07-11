import sys
from importlib import import_module
_implementation = import_module("novelwiki.modules.identity.adapters.outbound.tokens")
sys.modules[__name__] = _implementation
