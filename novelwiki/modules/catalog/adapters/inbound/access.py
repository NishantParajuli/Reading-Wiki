"""Catalog access transport compatibility wrappers."""

from ..outbound.access import (
    can_edit,
    can_read,
    fetch_novel,
    is_admin,
    require_editable,
    require_readable,
)

__all__ = [
    "can_edit", "can_read", "fetch_novel", "is_admin",
    "require_editable", "require_readable",
]
