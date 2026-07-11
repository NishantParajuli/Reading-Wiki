"""Compatibility alias for Work Management claim repository."""
import sys
from novelwiki.modules.work.adapters.outbound import claims as _implementation
sys.modules[__name__] = _implementation
