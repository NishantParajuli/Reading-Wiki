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


class LegacyReadingCeilingBridge:
    """Temporary Reading adapter until its public ceiling query is promoted."""

    def __init__(self, pool):
        self._pool = pool

    async def resolve(
        self, novel_id: int, principal: Principal, requested: float | None
    ) -> CeilingContext:
        from novelwiki.auth.access import require_effective_ceiling
        try:
            result = await require_effective_ceiling(
                novel_id, _user(principal), requested_ceiling=requested
            )
        except HTTPException as exc:
            from novelwiki.kernel.errors import NotFound
            if exc.status_code == 404:
                raise NotFound(str(exc.detail)) from exc
            raise _convert_http(exc) from exc
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT number,title FROM chapters "
                "WHERE novel_id=$1 AND number <= $2 "
                "ORDER BY number DESC LIMIT 1;",
                novel_id, result.effective_ceiling,
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


class LegacyAiCostBridge:
    def require_spend_allowed(self, principal: Principal) -> None:
        from novelwiki import quota
        try:
            quota.require_spend_allowed(_user(principal))
        except HTTPException as exc:
            raise _convert_http(exc) from exc

    @contextlib.asynccontextmanager
    async def concurrency_slot(self, principal: Principal, kind: str):
        from novelwiki import ai_limits
        try:
            async with ai_limits.concurrency_slot(_user(principal), kind):
                yield
        except HTTPException as exc:
            raise _convert_http(exc) from exc

    async def consume_rate(self, principal: Principal, kind: str) -> None:
        from novelwiki import ai_limits
        try:
            await ai_limits.consume_ask_rate(_user(principal), kind)
        except HTTPException as exc:
            raise _convert_http(exc) from exc


class LegacyCatalogEditBridge:
    def __init__(self, pool):
        self._pool = pool

    async def require_editable(self, novel_id: int, principal: Principal) -> None:
        from novelwiki.auth.access import require_editable
        try:
            await require_editable(novel_id, _user(principal))
        except HTTPException as exc:
            from novelwiki.kernel.errors import NotFound
            if exc.status_code == 404:
                raise NotFound(str(exc.detail)) from exc
            raise _convert_http(exc) from exc

    async def enable_codex(self, novel_id: int) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                "UPDATE novels SET codex_enabled=TRUE WHERE id=$1;", novel_id
            )


class BackendResolutionBridge:
    async def resolve(self, principal: Principal, requested: str) -> BackendDecision:
        from novelwiki.ai_backend.policy import resolve_backend
        from novelwiki.ai_backend.types import Workload
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
        from novelwiki.jobs import service
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
        from novelwiki.jobs import service
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
