from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class RateLimit:
    limit: int
    window_seconds: int


class RateLimitExceeded(Exception):
    def __init__(self, retry_after: int):
        super().__init__("rate limit exceeded")
        self.retry_after = max(1, retry_after)


def bucket_key(scope: str, value: str | None) -> str:
    normalized = (value or "").strip().lower()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"{scope}:{digest}"
