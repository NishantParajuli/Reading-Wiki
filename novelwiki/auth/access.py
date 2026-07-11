"""Passive compatibility exports for Catalog and Reading access policies."""

from novelwiki.modules.catalog.adapters.inbound.access import (
    can_edit,
    can_read,
    fetch_novel,
    is_admin,
    require_editable,
    require_readable,
)
from novelwiki.modules.reading.adapters.inbound.access import (
    CodexCeiling,
    require_effective_ceiling,
)

__all__ = [
    "CodexCeiling",
    "can_edit",
    "can_read",
    "fetch_novel",
    "is_admin",
    "require_editable",
    "require_effective_ceiling",
    "require_readable",
]
