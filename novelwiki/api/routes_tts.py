"""Compatibility alias for the Narration HTTP adapter."""

import sys

from novelwiki.modules.narration.adapters.inbound import http as _implementation

sys.modules[__name__] = _implementation
