"""Stable external compatibility alias for Identity quota operations."""

import sys

from novelwiki.modules.identity.adapters.outbound import quota_compat as _implementation

sys.modules[__name__] = _implementation
