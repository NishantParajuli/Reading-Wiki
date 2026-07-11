import sys
from importlib import import_module
_implementation = import_module("novelwiki.modules.acquisition.adapters.outbound.importer.ocr_client")
sys.modules[__name__] = _implementation
