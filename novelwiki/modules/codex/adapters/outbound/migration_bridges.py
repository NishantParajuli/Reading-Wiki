from __future__ import annotations

import contextlib

from fastapi import HTTPException

from novelwiki.kernel.errors import (
    Conflict, Forbidden, ProviderUnavailable, QuotaExceeded, ValidationFailed,
)
from novelwiki.modules.identity.public import Principal

from ...application.dto import ActiveCodexJob, BackendDecision, CeilingContext
from ...public import ChapterCeiling


def _user(principal: Principal) -> dict:
    return {
        "id": principal.user_id, "role": principal.role,
        "status": principal.status, "email_verified": principal.email_verified,
    }


def _convert_http(exc: HTTPException) -> Exception:
    kind = (
        ValidationFailed if exc.status_code == 422 else
        Forbidden if exc.status_code == 403 else
        QuotaExceeded if exc.status_code == 429 else
        Conflict if exc.status_code == 409 else ProviderUnavailable
    )
    return kind(str(exc.detail))


class ReadingCeilingGateway:
    """Temporary Reading adapter until its public ceiling query is promoted."""

    def __init__(self, pool):
        self._pool = pool

    async def resolve(
        self, novel_id: int, principal: Principal, requested: float | None
    ) -> CeilingContext:
        from novelwiki.modules.reading.public import require_effective_ceiling
        try:
            result = await require_effective_ceiling(
                novel_id, _user(principal), requested_ceiling=requested
            )
        except HTTPException as exc:
            from novelwiki.kernel.errors import NotFound
            if exc.status_code == 404:
                raise NotFound(str(exc.detail)) from exc
            raise _convert_http(exc) from exc
        from novelwiki.bootstrap.reading_migration import build_reading_codex_gateway
        row = await (await build_reading_codex_gateway()).chapter_at_or_before(
            novel_id, result.effective_ceiling
        )
        novel = result.novel
        return CeilingContext(
            ceiling=ChapterCeiling(float(result.effective_ceiling)),
            requested_ceiling=result.requested_ceiling,
            allowed_ceiling=float(result.allowed_ceiling),
            clamped=bool(result.clamped), chapter_count=int(result.chapter_count),
            min_chapter=float(result.min_chapter),
            max_chapter=float(result.max_chapter),
            novel_title=novel["title"], novel_blurb=novel.get("description") or "",
            ceiling_chapter=float(row["number"]) if row else None,
            ceiling_title=row["title"] if row else None,
        )


class AiCostGateway:
    def require_spend_allowed(self, principal: Principal) -> None:
        import novelwiki.modules.identity.public as quota
        try:
            quota.require_spend_allowed(_user(principal))
        except HTTPException as exc:
            raise _convert_http(exc) from exc

    @contextlib.asynccontextmanager
    async def concurrency_slot(self, principal: Principal, kind: str):
        import novelwiki.modules.ai_execution.public as ai_limits
        try:
            async with ai_limits.concurrency_slot(_user(principal), kind):
                yield
        except HTTPException as exc:
            raise _convert_http(exc) from exc

    async def consume_rate(self, principal: Principal, kind: str) -> None:
        import novelwiki.modules.ai_execution.public as ai_limits
        try:
            await ai_limits.consume_ask_rate(_user(principal), kind)
        except HTTPException as exc:
            raise _convert_http(exc) from exc


class BackendResolutionBridge:
    async def resolve(self, principal: Principal, requested: str) -> BackendDecision:
        from novelwiki.modules.ai_execution.public import Workload, resolve_backend
        try:
            decision = await resolve_backend(
                _user(principal), Workload.CODEX_EXTRACT, requested
            )
        except HTTPException as exc:
            raise _convert_http(exc) from exc
        fields = decision.as_job_fields()
        return BackendDecision(
            requested=fields["backend_requested"],
            resolved=fields["execution_backend"], reason=decision.reason,
            model=decision.model, policy_version=fields["backend_policy_version"],
            fallback_allowed=fields["backend_fallback_allowed"],
        )


class CodexWorkBridge:
    async def find_active(self, idempotency_key: str) -> ActiveCodexJob | None:
        from novelwiki.modules.work.public import service
        job = await service.find_active("codex_build", idempotency_key)
        if job is None:
            return None
        view = service.job_view(job)
        return ActiveCodexJob(
            job_id=int(job["id"]),
            execution_backend=view["execution_backend"],
            model=view["backend_model"],
        )

    async def schedule(
        self, *, novel_id: int, user_id: int, options: dict,
        idempotency_key: str, decision: BackendDecision,
        max_attempts: int | None,
    ) -> tuple[int, bool]:
        from novelwiki.modules.work.public import service
        try:
            return await service.create_job(
                "codex_build", novel_id=novel_id, user_id=user_id,
                options=options, idempotency_key=idempotency_key,
                quota_kind="codex_builds", quota_reserved=1,
                max_attempts=max_attempts,
                backend_requested=decision.requested,
                execution_backend=decision.resolved,
                backend_policy_version=decision.policy_version,
                backend_fallback_allowed=decision.fallback_allowed,
                backend_model=decision.model,
            )
        except service.ActiveJobLimitError as exc:
            raise QuotaExceeded(str(exc)) from exc
        except service.BackendPolicyChangedError as exc:
            raise Conflict(str(exc)) from exc


class CodexQuotaBridge:
    def __init__(self, service):
        self._service = service

    async def reserve(self, principal: Principal) -> None:
        await self._service.check_and_reserve(principal, "codex_builds", 1)

    async def refund(self, user_id: int) -> None:
        await self._service.refund(user_id, "codex_builds", 1)
