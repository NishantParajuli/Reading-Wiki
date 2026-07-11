"""Compatibility alias for Experience read models."""

import sys

from novelwiki.modules.experience.adapters.inbound import http as _implementation

sys.modules[__name__] = _implementation
