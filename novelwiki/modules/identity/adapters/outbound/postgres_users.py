from __future__ import annotations

from typing import Any

from novelwiki.modules.identity.domain.policies import normalize_username


async def unique_username(connection: Any, base: str) -> str:
    """Return the normalized base or its first available numbered variant."""
    base = normalize_username(base)
    if not await connection.fetchval("SELECT 1 FROM users WHERE username = $1;", base):
        return base
    for number in range(2, 10000):
        candidate = f"{base[:20]}_{number}"
        if not await connection.fetchval(
            "SELECT 1 FROM users WHERE username = $1;", candidate
        ):
            return candidate
    return normalize_username(base) + "_" + base[:4]
