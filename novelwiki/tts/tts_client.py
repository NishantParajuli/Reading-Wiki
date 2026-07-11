import sys
from novelwiki.modules.narration.adapters.outbound import sidecar as _implementation
sys.modules[__name__] = _implementation
