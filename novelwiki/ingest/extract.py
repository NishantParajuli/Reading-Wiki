import sys
from importlib import import_module
from novelwiki.bootstrap.codex_worker import wire_codex_worker_dependencies
wire_codex_worker_dependencies()
_implementation = import_module("novelwiki.modules.codex.adapters.outbound.ingest.extract")
sys.modules[__name__] = _implementation
