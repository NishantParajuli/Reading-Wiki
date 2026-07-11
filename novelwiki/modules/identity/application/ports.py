from __future__ import annotations

import datetime as dt
from typing import Protocol


class QuotaRepository(Protocol):
    async def get_usage(self, user_id: int, period: dt.date) -> dict[str, int]: ...
    async def bump(self, user_id: int, period: dt.date, kind: str, units: int) -> None: ...
    async def try_reserve(
        self, user_id: int, period: dt.date, kind: str, units: int, limit: int
    ) -> bool: ...
    async def refund(
        self, user_id: int, period: dt.date, kind: str, units: int
    ) -> int: ...


class SessionRepository(Protocol):
    async def load_active_user(self, token_hash: str) -> dict | None: ...


class TokenHasher(Protocol):
    def __call__(self, token: str) -> str: ...
