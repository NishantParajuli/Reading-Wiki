import sys
from novelwiki.modules.narration.adapters.inbound import worker as _implementation
sys.modules[__name__] = _implementation
