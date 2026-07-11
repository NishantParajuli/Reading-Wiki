"""Explicit dependency container; created by entrypoints, never used as a locator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ApplicationContainer:
    settings: Any
    audit_sink: Any


def build_container() -> ApplicationContainer:
    from novelwiki.platform.config import settings
    from novelwiki.platform.observability import LegacyAuditSink

    return ApplicationContainer(settings=settings, audit_sink=LegacyAuditSink())
