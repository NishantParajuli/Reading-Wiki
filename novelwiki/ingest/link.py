import sys
from importlib import import_module
_implementation = import_module("novelwiki.modules.codex.adapters.outbound.ingest.link")
sys.modules[__name__] = _implementation
