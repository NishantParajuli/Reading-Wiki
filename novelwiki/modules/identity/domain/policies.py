from __future__ import annotations

import re

from novelwiki.modules.identity.public import Principal

_USERNAME_RE = re.compile(r"[^a-z0-9_]+")


def normalize_username(raw: str) -> str:
    value = _USERNAME_RE.sub("_", (raw or "").strip().lower()).strip("_")
    return (value or "user")[:24]


def valid_username(name: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9_]{3,24}", name or ""))


def spend_allowed(principal: Principal) -> bool:
    return principal.is_admin or principal.email_verified


def is_admin(principal: Principal) -> bool:
    return principal.is_admin
