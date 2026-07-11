import sys
from importlib import import_module
_implementation = import_module("novelwiki.modules.codex.adapters.outbound.retrieval.fuse")
sys.modules[__name__] = _implementation
