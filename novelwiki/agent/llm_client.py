import sys
from importlib import import_module

_implementation = import_module(
    "novelwiki.modules.ai_execution.adapters.outbound.providers"
)
sys.modules[__name__] = _implementation
