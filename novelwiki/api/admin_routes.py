"""Compatibility alias for the Experience/Admin inbound adapter."""

import sys

from novelwiki.modules.experience.adapters.inbound import admin_http as _implementation

sys.modules[__name__] = _implementation
