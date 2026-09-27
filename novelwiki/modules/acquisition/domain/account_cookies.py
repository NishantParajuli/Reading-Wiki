"""Validate a browser export without retaining unrelated tracking credentials."""
from __future__ import annotations

import math
import re
from datetime import UTC, datetime

from novelwiki.kernel.errors import ValidationFailed

COOKIE_NAMES = frozenset({"TKEY", "LOGINKEY", "USERKEY"})
COOKIE_DOMAINS = frozenset({"novelpia.com", ".novelpia.com", "global.novelpia.com"})
MAX_EXPORT_BYTES = 65536


def normalize_novelpia_cookies(export: object) -> list[dict]:
    """Accept EditThisCookie exports; errors deliberately never include user input."""
    if not isinstance(export, list) or not export or len(export) > 100:
        raise ValidationFailed("Paste a cookie export containing between 1 and 100 cookies.")
    cookies = []
    seen = set()
    for item in export:
        if not isinstance(item, dict):
            raise ValidationFailed("Each exported cookie must be an object.")
        name = item.get("name")
        if not isinstance(name, str) or name not in COOKIE_NAMES:
            continue
        domain = item.get("domain")
        if not isinstance(domain, str) or domain not in COOKIE_DOMAINS:
            raise ValidationFailed("Login cookies must belong to novelpia.com or global.novelpia.com.")
        if name in seen:
            raise ValidationFailed("The export contains duplicate login cookies. Export cookies from the Novelpia Global page only.")
        value = item.get("value")
        if not isinstance(value, str) or not re.fullmatch(r"[\x21\x23-\x2b\x2d-\x3a\x3c-\x5b\x5d-\x7e]{1,8192}", value):
            raise ValidationFailed("A login cookie contains an empty or invalid value. Export your cookies again.")
        if item.get("path", "/") != "/":
            raise ValidationFailed("Novelpia login cookies must use the root path.")
        session = item.get("session", False)
        if not isinstance(session, bool):
            raise ValidationFailed("A login cookie has invalid session metadata.")
        expires = item.get("expirationDate")
        if expires is not None:
            if isinstance(expires, bool) or not isinstance(expires, (int, float)) or not math.isfinite(expires):
                raise ValidationFailed("A login cookie has an invalid expiry date.")
            try:
                datetime.fromtimestamp(expires, UTC)
            except (ValueError, OverflowError, OSError):
                raise ValidationFailed("A login cookie has an invalid expiry date.") from None
        cookies.append({"name": name, "value": value, "domain": domain,
                        "path": "/", "expires": None if session else expires})
        seen.add(name)
    if "TKEY" not in seen:
        raise ValidationFailed("The export is missing TKEY. Sign into Novelpia Global, then export its cookies again.")
    return sorted(cookies, key=lambda item: item["name"])


def cookie_metadata(cookies: list[dict], updated_at: datetime | None = None) -> dict:
    now = datetime.now(UTC).timestamp()
    return {
        "configured": bool(cookies),
        "usable": any(cookie["name"] == "TKEY" and
                      (cookie["expires"] is None or cookie["expires"] > now)
                      for cookie in cookies),
        "updated_at": updated_at.isoformat() if updated_at else None,
        "cookies": [{"name": cookie["name"], "domain": cookie["domain"],
                     "expires_at": datetime.fromtimestamp(cookie["expires"], UTC).isoformat()
                     if cookie["expires"] is not None else None}
                    for cookie in cookies],
    }
