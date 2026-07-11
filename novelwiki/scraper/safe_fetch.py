import sys
from importlib import import_module
_implementation = import_module("novelwiki.modules.acquisition.adapters.outbound.scraper.safe_fetch")
sys.modules[__name__] = _implementation
