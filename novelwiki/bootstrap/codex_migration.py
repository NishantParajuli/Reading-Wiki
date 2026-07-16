"""Composition root for the HTTP-facing Codex migration slice."""

from __future__ import annotations

import contextlib

from novelwiki.kernel.errors import (
    Conflict, Forbidden, NotFound, ProviderUnavailable, QuotaExceeded,
    ValidationFailed,
)


def _user(principal):
    return {
        "id": principal.user_id, "role": principal.role,
        "status": principal.status, "email_verified": principal.email_verified,
    }


def _convert_transport_error(exc: Exception) -> Exception:
    from novelwiki.kernel.errors import ApplicationError, RateLimited
    if isinstance(exc, RateLimited):
        return QuotaExceeded(str(exc))
    if isinstance(exc, ApplicationError):
        return exc
    status = getattr(exc, "status_code", None)
    kind = (
        ValidationFailed if status == 422 else
        Forbidden if status == 403 else
        QuotaExceeded if status == 429 else
        Conflict if status == 409 else ProviderUnavailable
    )
    return kind(str(getattr(exc, "detail", exc)))


async def build_codex_migration_service(agent_gateway=None):
    from novelwiki.bootstrap.ai_execution import wire_ai_policy
    wire_ai_policy()
    from novelwiki.modules.codex.adapters.outbound.agent_bridge import (
        CodexAgentGateway,
    )
    from novelwiki.modules.codex.adapters.outbound.postgres_queries import (
        PostgresCodexQueries, PostgresEntityMerger,
    )
    from novelwiki.modules.codex.application import (
        CodexCommandService, CodexMigrationService, CodexQueryService,
    )
    from novelwiki.modules.identity.adapters.outbound.postgres_quota import (
        PostgresQuotaRepository,
    )
    from novelwiki.modules.identity.application import QuotaService
    from novelwiki.modules.catalog.adapters.outbound.postgres import PostgresCatalogRepository
    from novelwiki.modules.catalog.application import (
        CatalogAccessService, CatalogTransactionService,
    )
    from novelwiki.modules.codex.application.dto import (
        ActiveCodexJob, BackendDecision, CeilingContext,
    )
    from novelwiki.modules.codex.public import ChapterCeiling
    from novelwiki.modules.reading.adapters.outbound.codex import (
        PostgresReadingCodexGateway,
    )
    from novelwiki.modules.reading.adapters.outbound.postgres import (
        PostgresReadingRepository,
    )
    from novelwiki.modules.reading.application import ReadingService
    from novelwiki.modules.ai_execution.adapters.outbound import limits as ai_limits
    from novelwiki.modules.ai_execution.adapters.outbound.policy import get_policy, resolve_backend
    from novelwiki.modules.ai_execution.domain.backend import Workload
    from novelwiki.modules.work.adapters.outbound import postgres as work_service
    from novelwiki.platform.config import settings
    from novelwiki.platform.database import init_db_pool

    pool = await init_db_pool()

    class ReadingCeilingBridge:
        async def resolve(self, novel_id, principal, requested):
            async with pool.acquire() as connection:
                try:
                    result = await ReadingService(
                        PostgresReadingRepository(connection),
                        CatalogAccessService(PostgresCatalogRepository(connection)),
                    ).effective_ceiling(novel_id, principal, requested)
                except NotFound:
                    raise
            row = await PostgresReadingCodexGateway(pool).chapter_at_or_before(
                novel_id, result.effective_ceiling
            )
            return CeilingContext(
                ceiling=ChapterCeiling(float(result.effective_ceiling)),
                requested_ceiling=result.requested_ceiling,
                allowed_ceiling=float(result.allowed_ceiling),
                clamped=bool(result.clamped),
                chapter_count=int(result.chapter_count),
                min_chapter=float(result.min_chapter),
                max_chapter=float(result.max_chapter),
                novel_title=result.novel.title or "",
                novel_blurb=result.novel.description or "",
                ceiling_chapter=float(row["number"]) if row else None,
                ceiling_title=row["title"] if row else None,
            )

    quota_service = QuotaService(PostgresQuotaRepository(pool=pool))

    class AiCostBridge:
        def require_spend_allowed(self, principal):
            quota_service.require_spend_allowed(principal)

        @contextlib.asynccontextmanager
        async def concurrency_slot(self, principal, kind):
            try:
                async with ai_limits.concurrency_slot(_user(principal), kind):
                    yield
            except Exception as exc:
                raise _convert_transport_error(exc) from exc

        async def consume_rate(self, principal, kind):
            try:
                await ai_limits.consume_ask_rate(_user(principal), kind)
            except Exception as exc:
                raise _convert_transport_error(exc) from exc

    class BackendBridge:
        async def resolve(self, principal, requested):
            try:
                decision = await resolve_backend(
                    _user(principal), Workload.CODEX_EXTRACT, requested
                )
            except Exception as exc:
                raise _convert_transport_error(exc) from exc
            fields = decision.as_job_fields()
            return BackendDecision(
                requested=fields["backend_requested"],
                resolved=fields["execution_backend"], reason=decision.reason,
                model=decision.model,
                policy_version=fields["backend_policy_version"],
                fallback_allowed=fields["backend_fallback_allowed"],
            )

    class WorkBridge:
        async def find_active(self, idempotency_key):
            job = await work_service.find_active("codex_build", idempotency_key)
            if job is None:
                return None
            view = work_service.job_view(job)
            return ActiveCodexJob(
                job_id=int(job["id"]),
                execution_backend=view["execution_backend"],
                model=view["backend_model"],
            )

        async def schedule(
            self, *, novel_id, user_id, options, idempotency_key,
            decision, max_attempts,
        ):
            try:
                return await work_service.create_job(
                    "codex_build", novel_id=novel_id, user_id=user_id,
                    options=options, idempotency_key=idempotency_key,
                    quota_kind="codex_builds", quota_reserved=1,
                    max_attempts=max_attempts,
                    backend_requested=decision.requested,
                    execution_backend=decision.resolved,
                    backend_policy_version=decision.policy_version,
                    backend_fallback_allowed=decision.fallback_allowed,
                    backend_model=decision.model, policy_lookup=get_policy,
                )
            except work_service.ActiveJobLimitError as exc:
                raise QuotaExceeded(str(exc)) from exc
            except work_service.BackendPolicyChangedError as exc:
                raise Conflict(str(exc)) from exc

    class QuotaBridge:
        async def reserve(self, principal):
            await quota_service.check_and_reserve(principal, "codex_builds", 1)

        async def refund(self, user_id):
            await quota_service.refund(user_id, "codex_builds", 1)

    class CatalogEditBridge:
        async def require_editable(self, novel_id, principal):
            async with pool.acquire() as connection:
                await CatalogAccessService(
                    PostgresCatalogRepository(connection)
                ).require_editable(novel_id, principal)

        async def enable_codex(self, novel_id):
            async with pool.acquire() as connection:
                async with connection.transaction():
                    await CatalogTransactionService(
                        PostgresCatalogRepository(connection)
                    ).enable_codex(novel_id)
    from novelwiki.bootstrap.codex_worker import build_codex_runtime
    queries = CodexQueryService(
        ReadingCeilingBridge(), PostgresCodexQueries(pool),
        agent_gateway or CodexAgentGateway(build_codex_runtime()), AiCostBridge(),
        ask_max_query_chars=settings.ASK_MAX_QUERY_CHARS,
        ask_requires_verified=settings.ASK_REQUIRE_VERIFIED,
        profile_requires_verified=settings.ENTITY_PROFILE_SYNTH_REQUIRE_VERIFIED,
        profile_model=settings.MODEL_PRO,
    )
    commands = CodexCommandService(
        CatalogEditBridge(), BackendBridge(), WorkBridge(), QuotaBridge(),
        PostgresEntityMerger(pool), settings.AGY_MAX_ATTEMPTS,
        pipeline_version=settings.CODEX_PIPELINE_VERSION,
    )
    return CodexMigrationService(queries, commands)


def codex_principal_from_user(user: dict):
    from novelwiki.modules.identity.adapters.principals import principal_from_user
    return principal_from_user(user)


async def build_codex_principal_factory():
    """Dependency-provider shape expected by the native inbound adapter."""
    return codex_principal_from_user


__all__ = [
    "build_codex_migration_service", "build_codex_principal_factory",
    "codex_principal_from_user",
]
