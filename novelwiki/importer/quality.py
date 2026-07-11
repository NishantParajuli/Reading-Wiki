import sys
from importlib import import_module

_implementation = import_module("novelwiki.modules.acquisition.domain.quality")
sys.modules[__name__] = _implementation
