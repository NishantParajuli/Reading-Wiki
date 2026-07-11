import sys
from importlib import import_module

_implementation = import_module("novelwiki.modules.acquisition.domain.document")
sys.modules[__name__] = _implementation
