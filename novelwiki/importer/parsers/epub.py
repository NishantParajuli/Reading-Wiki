import sys
from importlib import import_module
_implementation = import_module("novelwiki.modules.acquisition.adapters.outbound.importer.parsers.epub")
sys.modules[__name__] = _implementation
