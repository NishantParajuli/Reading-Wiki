import sys
from importlib import import_module

_implementation = import_module("novelwiki.modules.acquisition.domain.cleanup")
sys.modules[__name__] = _implementation
