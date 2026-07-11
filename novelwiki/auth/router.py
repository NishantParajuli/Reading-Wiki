"""Compatibility alias for the Identity HTTP adapter."""

import sys

from novelwiki.modules.identity.adapters.inbound import http as _implementation

sys.modules[__name__] = _implementation
