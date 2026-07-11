from __future__ import annotations

from fastapi import HTTPException

from novelwiki.kernel.errors import Conflict, Forbidden, ProviderUnavailable, QuotaExceeded, ValidationFailed
from novelwiki.modules.identity.public import Principal

from ...application.ports import ActiveTranslationJob, BackendDecision


class BackendResolutionBridge:
    async def resolve(self, principal: Principal, requested: str) -> BackendDecision:
        from novelwiki.modules.ai_execution.public import Workload, resolve_backend
        try:
            decision = await resolve_backend(
                {"id": principal.user_id, "status": principal.status},
                Workload.TRANSLATE_BATCH,
                requested,
            )
        except HTTPException as exc:
            error = ValidationFailed if exc.status_code == 422 else Forbidden if exc.status_code == 403 else QuotaExceeded if exc.status_code == 429 else ProviderUnavailable
            raise error(str(exc.detail)) from exc
        fields = decision.as_job_fields()
        return BackendDecision(
            requested=fields["backend_requested"],
            resolved=fields["execution_backend"],
            reason=decision.reason,
            model=decision.model,
            policy_version=fields["backend_policy_version"],
            fallback_allowed=fields["backend_fallback_allowed"],
        )


class TranslationWorkBridge:
    async def find_active(self, idempotency_key: str) -> ActiveTranslationJob | None:
        from novelwiki.modules.work.public import service
        job = await service.find_active("translate", idempotency_key)
        if job is None:
            return None
        view = service.job_view(job)
        return ActiveTranslationJob(
            job_id=int(job["id"]),
            chapters=int((job.get("progress") or {}).get("total") or 0),
            execution_backend=view["execution_backend"],
            model=view["backend_model"],
        )

    async def schedule(
        self, *, novel_id: int, user_id: int, options: dict,
        idempotency_key: str, decision: BackendDecision,
        quota_reserved: int, max_attempts: int | None,
    ) -> tuple[int, bool]:
        from novelwiki.modules.work.public import service
        try:
            return await service.create_job(
                "translate", novel_id=novel_id, user_id=user_id,
                options=options, idempotency_key=idempotency_key,
                quota_kind="translated_chapters" if quota_reserved else None,
                quota_reserved=quota_reserved, max_attempts=max_attempts,
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


class TranslationQuotaBridge:
    def __init__(self, service):
        self._service = service

    async def check_available(self, principal: Principal, units: int) -> None:
        await self._service.check_available(principal, "translated_chapters", units)

    async def reserve(self, principal: Principal, units: int) -> None:
        await self._service.check_and_reserve(principal, "translated_chapters", units)

    async def refund(self, user_id: int, units: int) -> None:
        await self._service.refund(user_id, "translated_chapters", units)
