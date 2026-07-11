import sys
from novelwiki.modules.narration.adapters.outbound import coverage as _implementation
sys.modules[__name__] = _implementation
