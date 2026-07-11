from __future__ import annotations

import datetime as dt

from novelwiki.kernel.errors import Forbidden, QuotaExceeded
from novelwiki.modules.identity.domain.policies import spend_allowed
from novelwiki.modules.identity.public import Principal

from .ports import QuotaRepository

QUOTA_KINDS = (
    "translated_chapters",
    "ocr_pages",
    "codex_builds",
    "tts_chapters",
)
SPEND_FORBIDDEN_DETAIL = (
    "Verify your email to use scrape, translation, OCR, codex, or import features."
)


def current_period() -> dt.date:
    return dt.date.today().replace(day=1)


class QuotaService:
    def __init__(self, repository: QuotaRepository):
        self._repository = repository

    @staticmethod
    def validate_kind(kind: str) -> None:
        if kind not in QUOTA_KINDS:
            raise ValueError(f"unknown quota kind: {kind}")

    @staticmethod
    def require_spend_allowed(principal: Principal) -> None:
        if not spend_allowed(principal):
            raise Forbidden(SPEND_FORBIDDEN_DETAIL)

    @staticmethod
    def _limit(principal: Principal, kind: str) -> int:
        try:
            return int(principal.quota_limits[kind])
        except KeyError as exc:
            raise ValueError(f"quota limit missing for kind: {kind}") from exc

    async def get_usage(self, user_id: int) -> dict[str, int]:
        return await self._repository.get_usage(user_id, current_period())

    async def usage_and_limits(self, principal: Principal) -> dict:
        used = await self.get_usage(principal.user_id)
        limits = {kind: self._limit(principal, kind) for kind in QUOTA_KINDS}
        return {
            "period": current_period().isoformat(),
            "unlimited": principal.is_admin,
            "usage": used,
            "limits": limits,
            "remaining": {
                kind: None if principal.is_admin else max(0, limits[kind] - used[kind])
                for kind in QUOTA_KINDS
            },
        }

    async def remaining(self, principal: Principal, kind: str) -> int | None:
        self.validate_kind(kind)
        if principal.is_admin:
            return None
        used = (await self.get_usage(principal.user_id))[kind]
        return max(0, self._limit(principal, kind) - used)

    async def check_available(
        self, principal: Principal, kind: str, units: int = 1
    ) -> None:
        self.validate_kind(kind)
        self.require_spend_allowed(principal)
        if units <= 0 or principal.is_admin:
            return
        limit = self._limit(principal, kind)
        used = (await self.get_usage(principal.user_id))[kind]
        if used + units > limit:
            raise QuotaExceeded(self._quota_detail(kind, limit))

    async def reserve(
        self, principal: Principal, kind: str, units: int = 1
    ) -> bool:
        self.validate_kind(kind)
        if units <= 0:
            return True
        if principal.is_admin:
            await self._repository.bump(
                principal.user_id, current_period(), kind, units
            )
            return True
        if not spend_allowed(principal):
            return False
        return await self._repository.try_reserve(
            principal.user_id,
            current_period(),
            kind,
            units,
            self._limit(principal, kind),
        )

    async def check_and_reserve(
        self, principal: Principal, kind: str, units: int = 1
    ) -> None:
        self.validate_kind(kind)
        self.require_spend_allowed(principal)
        if not await self.reserve(principal, kind, units):
            raise QuotaExceeded(
                self._quota_detail(kind, self._limit(principal, kind))
            )

    async def refund(self, user_id: int, kind: str, units: int = 1) -> int:
        self.validate_kind(kind)
        if user_id is None or units <= 0:
            return 0
        return await self._repository.refund(
            user_id, current_period(), kind, units
        )

    @staticmethod
    def _quota_detail(kind: str, limit: int) -> str:
        label = kind.replace("_", " ")
        return (
            f"Monthly quota reached for {label} ({limit}/mo). "
            "Ask an admin to raise your limit."
        )
