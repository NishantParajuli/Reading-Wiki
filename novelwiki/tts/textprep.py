import sys
from novelwiki.modules.narration.domain import textprep as _implementation
sys.modules[__name__] = _implementation
