import sys
from importlib import import_module

_implementation = import_module(
    "novelwiki.modules.translation.adapters.outbound.legacy"
)
sys.modules[__name__] = _implementation
