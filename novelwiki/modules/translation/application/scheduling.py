from __future__ import annotations

from dataclasses import dataclass

from novelwiki.kernel.errors import Conflict, QuotaExceeded
from novelwiki.modules.identity.public import Principal

from .ports import (
    BackendResolutionPort, CatalogAccessPort, ReadingTranslationPort,
    TranslationQuotaPort, TranslationWorkPort,
)


@dataclass(frozen=True)
class ScheduleTranslation:
    from_chapter: float | None = None
    to_chapter: float | None = None
    force: bool = False
    seed_from_codex: bool = False
    ai_backend: str = "auto"


class TranslationSchedulingService:
    def __init__(
        self, catalog: CatalogAccessPort, reading: ReadingTranslationPort,
        backend: BackendResolutionPort, work: TranslationWorkPort,
        quota: TranslationQuotaPort, agy_max_attempts: int,
    ):
        self._catalog = catalog
        self._reading = reading
        self._backend = backend
        self._work = work
        self._quota = quota
        self._agy_max_attempts = agy_max_attempts

    async def schedule(
        self, novel_id: int, principal: Principal, command: ScheduleTranslation
    ) -> dict:
        await self._catalog.require_editable(novel_id, principal)
        idem = (
            f"translate:novel{novel_id}:{command.from_chapter}:{command.to_chapter}:"
            f"{int(command.force)}:seed{int(command.seed_from_codex)}"
        )
        existing = await self._work.find_active(idem)
        if existing is not None:
            return {
                "status": "success",
                "message": "A translation for this range is already running.",
                "job_id": existing.job_id, "deduped": True,
                "chapters": existing.chapters,
                "execution_backend": existing.execution_backend,
                "model": existing.model, "backend_reason": "already_active",
            }

        decision = await self._backend.resolve(principal, command.ai_backend)
        pending = await self._reading.count_pending(
            novel_id, command.from_chapter, command.to_chapter, command.force
        )
        reserved = pending if decision.resolved == "agy" else 0
        if reserved:
            await self._quota.reserve(principal, reserved)
        else:
            await self._quota.check_available(principal, pending)
        try:
            job_id, created = await self._work.schedule(
                novel_id=novel_id,
                user_id=principal.user_id,
                options={
                    "from_chapter": command.from_chapter,
                    "to_chapter": command.to_chapter,
                    "force": command.force,
                    "seed_from_codex": command.seed_from_codex,
                },
                idempotency_key=idem,
                decision=decision,
                quota_reserved=reserved,
                max_attempts=self._agy_max_attempts if reserved else None,
            )
        except (QuotaExceeded, Conflict):
            if reserved:
                await self._quota.refund(principal.user_id, reserved)
            raise
        if not created and reserved:
            await self._quota.refund(principal.user_id, reserved)
        return {
            "status": "success",
            "message": "Translation job scheduled." if created else "A translation for this range is already running.",
            "job_id": job_id, "deduped": not created, "chapters": pending,
            "execution_backend": decision.resolved, "model": decision.model,
            "backend_reason": decision.reason,
        }
