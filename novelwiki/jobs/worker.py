"""Compatibility alias for the Work Management worker adapter."""
import sys
from novelwiki.modules.work.adapters.inbound import worker as _implementation
sys.modules[__name__] = _implementation
