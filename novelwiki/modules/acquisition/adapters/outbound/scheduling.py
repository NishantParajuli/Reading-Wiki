from __future__ import annotations

from collections.abc import Awaitable, Callable

from novelwiki.kernel.errors import ValidationFailed

from .scraper.safe_fetch import SafeFetchError


class SafeSourceUrlAdapter:
    def __init__(self, validator: Callable[[str], Awaitable[str]]):
        self._validator = validator

    async def validate(self, url: str) -> str:
        try:
            return await self._validator(url)
        except SafeFetchError as exc:
            raise ValidationFailed(f"Unsafe source URL: {exc}") from exc


class DurableScrapeWorkAdapter:
    def __init__(self, create_job: Callable[..., Awaitable[tuple[int, bool]]]):
        self._create_job = create_job

    async def schedule(
        self, *, novel_id: int, user_id: int, options: dict, idempotency_key: str
    ) -> tuple[int, bool]:
        return await self._create_job(
            "scrape",
            novel_id=novel_id,
            user_id=user_id,
            options=options,
            idempotency_key=idempotency_key,
        )
