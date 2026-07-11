from __future__ import annotations

from novelwiki.kernel.errors import Conflict, Forbidden, ProviderUnavailable, QuotaExceeded, ValidationFailed
from novelwiki.modules.identity.public import Principal

from ...application.ports import ActiveTranslationJob, BackendDecision


class BackendResolutionBridge:
    def __init__(self, resolve_backend, workload):
        self._resolve_backend = resolve_backend
        self._workload = workload

    async def resolve(self, principal: Principal, requested: str) -> BackendDecision:
        try:
            decision = await self._resolve_backend(
                {"id": principal.user_id, "status": principal.status},
                self._workload,
                requested,
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status is None:
                raise
            error = ValidationFailed if status == 422 else Forbidden if status == 403 else QuotaExceeded if status == 429 else ProviderUnavailable
            raise error(str(getattr(exc, "detail", exc))) from exc
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
    def __init__(self, service, active_limit_error, policy_changed_error):
        self._service = service
        self._active_limit_error = active_limit_error
        self._policy_changed_error = policy_changed_error

    async def find_active(self, idempotency_key: str) -> ActiveTranslationJob | None:
        job = await self._service.find_active("translate", idempotency_key)
        if job is None:
            return None
        view = self._service.job_view(job)
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
        try:
            return await self._service.create_job(
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
        except self._active_limit_error as exc:
            raise QuotaExceeded(str(exc)) from exc
        except self._policy_changed_error as exc:
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
