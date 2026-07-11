"""Compatibility alias for Work Management persistence/application adapter."""
import sys
from novelwiki.modules.work.adapters.outbound import postgres as _implementation
sys.modules[__name__] = _implementation
