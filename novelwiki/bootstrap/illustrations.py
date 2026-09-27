"""Composition for Codex illustration authorization, scheduling and host rendering."""

from __future__ import annotations

from novelwiki.kernel.errors import Forbidden, QuotaExceeded


async def build_illustration_service():
    from novelwiki.bootstrap.ai_execution import wire_ai_policy
    from novelwiki.modules.ai_execution.adapters.outbound.policy import (
        get_policy,
        resolve_backend,
    )
    from novelwiki.modules.ai_execution.domain.backend import Workload
    from novelwiki.modules.catalog.adapters.outbound.postgres import (
        PostgresCatalogRepository,
    )
    from novelwiki.modules.catalog.application import CatalogAccessService
    from novelwiki.modules.codex.application.illustrations import IllustrationService
    from novelwiki.modules.codex.adapters.outbound.illustration_store import (
        IllustrationStore,
    )
    from novelwiki.modules.reading.adapters.outbound.postgres import (
        PostgresReadingRepository,
    )
    from novelwiki.modules.reading.adapters.outbound.codex import (
        PostgresReadingCodexGateway,
    )
    from novelwiki.modules.reading.application import ReadingService
    from novelwiki.modules.work.adapters.outbound import postgres as work
    from novelwiki.platform.database import init_db_pool

    wire_ai_policy()
    pool = await init_db_pool()

    async def access(novel_id, chapter, principal, *, edit=False):
        async with pool.acquire() as conn:
            catalog = CatalogAccessService(PostgresCatalogRepository(conn))
            if edit:
                await catalog.require_editable(novel_id, principal)
            result = await ReadingService(
                PostgresReadingRepository(conn), catalog
            ).effective_ceiling(novel_id, principal, chapter)
            if chapter > result.allowed_ceiling:
                raise Forbidden(
                    "Read this chapter before viewing or generating its illustrations."
                )

    async def grant(principal):
        # Explicit subscription selection never falls back to a billed API.
        if not principal.email_verified and not principal.is_admin:
            raise Forbidden("Verify your email before generating illustrations.")
        return await resolve_backend(
            {
                "id": principal.user_id,
                "role": principal.role,
                "status": principal.status,
                "email_verified": principal.email_verified,
            },
            Workload.CODEX_EXTRACT,
            "openai_codex",
            enforce_concurrency=False,
        )

    async def schedule(novel_id, chapter, principal, count, style, digest, decision):
        try:
            job_id, created = await work.create_job(
                "codex_illustrate",
                novel_id=novel_id,
                user_id=principal.user_id,
                options={
                    "chapter": chapter,
                    "count": count,
                    "style": style,
                    "source_hash": digest,
                },
                idempotency_key=f"illustrate:{principal.user_id}:{novel_id}:{chapter}:{style}:{count}:{digest}",
                max_attempts=2,
                backend_requested="openai_codex",
                execution_backend="openai_codex",
                backend_policy_version=decision.policy_version,
                backend_fallback_allowed=False,
                backend_model="gpt-6-luna",
                policy_lookup=get_policy,
            )
        except work.ActiveJobLimitError as exc:
            raise QuotaExceeded(str(exc)) from exc
        except work.BackendPolicyChangedError as exc:
            raise Forbidden(str(exc)) from exc
        return {"job_id": job_id, "created": created}

    async def latest(novel_id, chapter, user_id):
        for job in await work.list_jobs(
            novel_id=novel_id, user_id=user_id, kind="codex_illustrate", limit=100
        ):
            if (job.get("options") or {}).get("chapter") == chapter:
                return {
                    "id": job["id"],
                    "status": job["status"],
                    "stage": job.get("stage"),
                    "error": job.get("error"),
                    "progress": job.get("progress"),
                }
        return None

    return IllustrationService(
        access=access,
        snapshot=PostgresReadingCodexGateway(pool).chapter_snapshot,
        store=IllustrationStore(pool),
        grant=grant,
        schedule=schedule,
        latest=latest,
    )


async def execute_illustration_job(job, preflight, context):
    from novelwiki.modules.codex.application.illustration_worker import (
        IllustrationWorker,
    )
    from novelwiki.modules.codex.adapters.outbound.illustration_store import (
        IllustrationStore,
    )
    from novelwiki.modules.reading.adapters.outbound.codex import (
        PostgresReadingCodexGateway,
    )
    from novelwiki.modules.ai_execution.adapters.outbound.openai_codex.illustration_runner import (
        IllustrationRenderer,
    )
    from novelwiki.modules.work.adapters.outbound import postgres as work
    from novelwiki.platform.database import init_db_pool

    pool = await init_db_pool()
    renderer = IllustrationRenderer(job, preflight, work)
    worker = IllustrationWorker(
        store=IllustrationStore(pool),
        snapshot=PostgresReadingCodexGateway(pool).chapter_snapshot,
        renderer=renderer,
        progress=context.set_progress,
        cancel=context.bail_if_canceled,
    )
    return await worker.execute(job)
