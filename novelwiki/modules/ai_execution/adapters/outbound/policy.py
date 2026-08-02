"""Admin-owned subscription grants and server-side backend resolution.

No client value can create an entitlement. Routes pass a server-owned workload
enum, and each dedicated worker repeats this authorization immediately before it
starts an authenticated CLI process.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from novelwiki.kernel.errors import (
    Forbidden,
    NotFound,
    ProviderUnavailable,
    RateLimited,
    ValidationFailed,
)
from novelwiki.modules.ai_execution.domain.backend import (
    IMPLEMENTED_AGY_WORKLOADS,
    IMPLEMENTED_OPENAI_CODEX_WORKLOADS,
    BackendDecision,
    ExecutionBackend,
    RequestedBackend,
    Workload,
    workload_for_job_kind,
)
from novelwiki.platform.config import settings
from novelwiki.platform.database import get_db_pool
from novelwiki.platform.observability import audit


class PolicyDependencies(Protocol):
    async def active_job_count(self, user_id: int, backend: str = "agy") -> int: ...
    async def user_exists(self, user_id: int) -> bool: ...
    async def revoked_job_ids(
        self, user_id: int, kinds: list[str], backend: str = "agy"
    ) -> list[int]: ...
    async def cancel_job(self, job_id: int) -> bool: ...


_dependencies: PolicyDependencies | None = None


def configure_policy_dependencies(dependencies: PolicyDependencies) -> None:
    global _dependencies
    _dependencies = dependencies


def _deps() -> PolicyDependencies:
    if _dependencies is None:
        raise RuntimeError("AI policy dependencies were not wired by the composition root")
    return _dependencies


def _requested(value: str | RequestedBackend) -> RequestedBackend:
    try:
        return value if isinstance(value, RequestedBackend) else RequestedBackend(str(value))
    except ValueError as exc:
        raise ValidationFailed(
            "ai_backend must be auto, api, agy, or openai_codex."
        ) from exc


def _provider_fields(backend: ExecutionBackend) -> tuple[str, str, str]:
    if backend is ExecutionBackend.AGY:
        return "agy_enabled", "agy_workloads", "max_concurrent_agy_jobs"
    if backend is ExecutionBackend.OPENAI_CODEX:
        return (
            "openai_codex_enabled",
            "openai_codex_workloads",
            "max_concurrent_openai_codex_jobs",
        )
    raise ValueError("API does not have a subscription grant")


def _implemented(backend: ExecutionBackend) -> frozenset[Workload]:
    if backend is ExecutionBackend.AGY:
        return IMPLEMENTED_AGY_WORKLOADS
    if backend is ExecutionBackend.OPENAI_CODEX:
        return IMPLEMENTED_OPENAI_CODEX_WORKLOADS
    return frozenset()


def _globally_enabled(backend: ExecutionBackend) -> bool:
    if backend is ExecutionBackend.AGY:
        return settings.AGY_ENABLED
    if backend is ExecutionBackend.OPENAI_CODEX:
        return settings.OPENAI_CODEX_ENABLED
    return True


def _workload_globally_enabled(workload: Workload, backend: ExecutionBackend) -> bool:
    if workload is not Workload.CODEX_EXTRACT:
        return True
    if backend is ExecutionBackend.AGY:
        return settings.AGY_CODEX_ENABLED
    if backend is ExecutionBackend.OPENAI_CODEX:
        return settings.OPENAI_CODEX_CODEX_ENABLED
    return True


def _provider_name(backend: ExecutionBackend) -> str:
    return "Antigravity" if backend is ExecutionBackend.AGY else "OpenAI Codex"


def model_for(workload: Workload, backend: ExecutionBackend) -> str | None:
    if backend is ExecutionBackend.AGY:
        return {
            Workload.TRANSLATE_BATCH: settings.AGY_MODEL_TRANSLATE,
            Workload.CODEX_EXTRACT: settings.AGY_MODEL_CODEX,
            Workload.SEGMENT_IMPORT: settings.AGY_MODEL_SEGMENT,
            Workload.OCR_PAGES: settings.AGY_MODEL_OCR,
        }.get(workload)
    if backend is ExecutionBackend.OPENAI_CODEX:
        return {
            Workload.TRANSLATE_BATCH: settings.OPENAI_CODEX_MODEL_TRANSLATE,
            Workload.CODEX_EXTRACT: settings.OPENAI_CODEX_MODEL_CODEX,
        }.get(workload)
    return {
        Workload.TRANSLATE_BATCH: settings.MODEL_TRANSLATE,
        Workload.CODEX_EXTRACT: settings.MODEL_FLASH,
        Workload.SEGMENT_IMPORT: settings.SEGMENT_MODEL,
        Workload.OCR_PAGES: settings.GEMINI_VISION_MODEL,
        Workload.ASK: settings.MODEL_PRO,
        Workload.PROFILE_SYNTHESIS: settings.MODEL_PRO,
    }.get(workload)


async def get_policy(user_id: int) -> dict | None:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT * FROM user_ai_backend_policies WHERE user_id=$1;", user_id
        )
    return dict(row) if row else None


async def worker_available(
    backend: ExecutionBackend | str = ExecutionBackend.AGY,
) -> bool:
    """A recent healthy heartbeat is a capability signal, never an entitlement."""
    backend = ExecutionBackend(backend)
    if not _globally_enabled(backend):
        return False
    ttl = (
        settings.AGY_WORKER_HEALTH_TTL_SECONDS
        if backend is ExecutionBackend.AGY
        else settings.OPENAI_CODEX_WORKER_HEALTH_TTL_SECONDS
    )
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        return bool(
            await conn.fetchval(
                """
                SELECT EXISTS(
                  SELECT 1 FROM ai_worker_heartbeats
                  WHERE backend=$1 AND status='healthy'
                    AND heartbeat_at >= now() - $2::interval
                );
                """,
                backend.value,
                timedelta(seconds=ttl),
            )
        )


async def capability_for_user(user_id: int) -> dict:
    policy = await get_policy(user_id)

    async def capability(backend: ExecutionBackend) -> dict:
        enabled_key, workloads_key, _ = _provider_fields(backend)
        enabled = bool(policy and policy.get(enabled_key))
        return {
            "enabled": enabled,
            "default_backend": policy.get("default_backend", "api") if policy else "api",
            "workloads": list(policy.get(workloads_key) or []) if policy else [],
            "fallback_to_api": bool(policy and policy.get("fallback_to_api")),
            "available": enabled and await worker_available(backend),
        }

    return {
        "agy": await capability(ExecutionBackend.AGY),
        "openai_codex": await capability(ExecutionBackend.OPENAI_CODEX),
    }


async def resolve_backend(
    user: dict,
    workload: Workload,
    requested: str | RequestedBackend = RequestedBackend.AUTO,
    *,
    enforce_concurrency: bool = True,
) -> BackendDecision:
    """Resolve one immutable job decision after normal product authorization."""
    req = _requested(requested)
    if req is RequestedBackend.API:
        return BackendDecision(
            req,
            ExecutionBackend.API,
            workload,
            "explicit_api",
            None,
            False,
            model_for(workload, ExecutionBackend.API),
        )

    policy = await get_policy(int(user["id"]))
    if req is RequestedBackend.AUTO and policy is None:
        reason = "global_disabled" if not settings.AGY_ENABLED else "not_granted"
        return BackendDecision(
            req, ExecutionBackend.API, workload, reason, None, False,
            model_for(workload, ExecutionBackend.API),
        )
    selected = (
        ExecutionBackend(req.value)
        if req is not RequestedBackend.AUTO
        else ExecutionBackend((policy or {}).get("default_backend", "api"))
    )
    if selected is ExecutionBackend.API:
        return BackendDecision(
            req,
            selected,
            workload,
            "user_policy_default_api",
            int(policy["policy_version"]) if policy else None,
            False,
            model_for(workload, selected),
        )

    name = _provider_name(selected)
    if not _globally_enabled(selected):
        if req is not RequestedBackend.AUTO:
            raise ProviderUnavailable(f"{name} is temporarily unavailable.")
        return BackendDecision(
            req, ExecutionBackend.API, workload, "global_disabled", None, False,
            model_for(workload, ExecutionBackend.API),
        )
    if not _workload_globally_enabled(workload, selected):
        if req is not RequestedBackend.AUTO:
            raise ProviderUnavailable(f"{name} Codex extraction is temporarily disabled.")
        return BackendDecision(
            req, ExecutionBackend.API, workload, "workload_disabled", None, False,
            model_for(workload, ExecutionBackend.API),
        )

    enabled_key, workloads_key, concurrency_key = _provider_fields(selected)
    implemented = _implemented(selected)
    granted = bool(
        policy
        and policy.get(enabled_key)
        and workload.value in (policy.get(workloads_key) or [])
        and workload in implemented
    )
    if not granted:
        if req is not RequestedBackend.AUTO:
            raise Forbidden(f"{name} is not enabled for this workload.")
        reason = "workload_unimplemented" if workload not in implemented else "not_granted"
        return BackendDecision(
            req, ExecutionBackend.API, workload, reason, None, False,
            model_for(workload, ExecutionBackend.API),
        )

    if user.get("status", "active") != "active":
        raise Forbidden("This account cannot schedule AI work.")
    if enforce_concurrency:
        active = await _deps().active_job_count(int(user["id"]), selected.value)
        if active >= int(policy.get(concurrency_key) or 1):
            raise RateLimited(f"Your {name} queue limit is already in use.")

    return BackendDecision(
        req,
        selected,
        workload,
        f"explicit_{selected.value}"
        if req is not RequestedBackend.AUTO
        else "user_policy_default",
        int(policy["policy_version"]),
        bool(policy.get("fallback_to_api")),
        model_for(workload, selected),
    )


async def reauthorize_job(job: dict, user: dict) -> tuple[bool, str]:
    """Recheck current grant/status just before a subscription subprocess starts."""
    try:
        backend = ExecutionBackend(job.get("execution_backend", "agy"))
    except ValueError:
        return False, "backend_invalid"
    if backend is ExecutionBackend.API or not _globally_enabled(backend):
        return False, "global_disabled"
    if not user or user.get("status") != "active":
        return False, "user_inactive"
    workload = workload_for_job_kind(job.get("kind", ""))
    if workload is None or workload not in _implemented(backend):
        return False, "workload_unimplemented"
    if not _workload_globally_enabled(workload, backend):
        return False, "workload_disabled"
    policy = await get_policy(int(user["id"]))
    enabled_key, workloads_key, _ = _provider_fields(backend)
    if not policy or not policy.get(enabled_key):
        return False, "grant_revoked"
    if workload.value not in (policy.get(workloads_key) or []):
        return False, "workload_revoked"
    changed = int(policy["policy_version"]) != int(job.get("backend_policy_version") or 0)
    return True, "policy_version_changed" if changed else "ok"


async def upsert_policy(user_id: int, values: dict, admin_id: int) -> dict:
    agy_workloads = sorted(set(values.get("agy_workloads") or []))
    openai_workloads = sorted(set(values.get("openai_codex_workloads") or []))
    unknown = (set(agy_workloads) | set(openai_workloads)) - {w.value for w in Workload}
    if unknown:
        raise ValidationFailed(f"Unknown AI workload(s): {', '.join(sorted(unknown))}.")

    agy_enabled = bool(values.get("agy_enabled", False))
    openai_enabled = bool(values.get("openai_codex_enabled", False))
    default = values.get("default_backend", "api")
    if (
        default not in ("api", "agy", "openai_codex")
        or (default == "agy" and not agy_enabled)
        or (default == "openai_codex" and not openai_enabled)
    ):
        raise ValidationFailed(
            "A subscription backend can be the default only while its access is enabled."
        )
    agy_concurrency = int(values.get("max_concurrent_agy_jobs", 1))
    openai_concurrency = int(values.get("max_concurrent_openai_codex_jobs", 1))
    if not 1 <= agy_concurrency <= 4:
        raise ValidationFailed("max_concurrent_agy_jobs must be between 1 and 4.")
    if not 1 <= openai_concurrency <= 4:
        raise ValidationFailed(
            "max_concurrent_openai_codex_jobs must be between 1 and 4."
        )

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            if not await _deps().user_exists(user_id):
                raise NotFound("User not found.")
            previous = await conn.fetchrow(
                "SELECT * FROM user_ai_backend_policies WHERE user_id=$1 FOR UPDATE;",
                user_id,
            )
            row = await conn.fetchrow(
                """
                INSERT INTO user_ai_backend_policies
                  (user_id,agy_enabled,openai_codex_enabled,default_backend,
                   agy_workloads,openai_codex_workloads,fallback_to_api,
                   max_concurrent_agy_jobs,max_concurrent_openai_codex_jobs,notes,granted_by)
                VALUES ($1,$2,$3,$4,$5::text[],$6::text[],$7,$8,$9,$10,$11)
                ON CONFLICT (user_id) DO UPDATE SET
                  agy_enabled=EXCLUDED.agy_enabled,
                  openai_codex_enabled=EXCLUDED.openai_codex_enabled,
                  default_backend=EXCLUDED.default_backend,
                  agy_workloads=EXCLUDED.agy_workloads,
                  openai_codex_workloads=EXCLUDED.openai_codex_workloads,
                  fallback_to_api=EXCLUDED.fallback_to_api,
                  max_concurrent_agy_jobs=EXCLUDED.max_concurrent_agy_jobs,
                  max_concurrent_openai_codex_jobs=EXCLUDED.max_concurrent_openai_codex_jobs,
                  notes=EXCLUDED.notes,granted_by=EXCLUDED.granted_by,
                  policy_version=user_ai_backend_policies.policy_version + 1,updated_at=now()
                RETURNING *;
                """,
                user_id,
                agy_enabled,
                openai_enabled,
                default,
                agy_workloads,
                openai_workloads,
                bool(values.get("fallback_to_api", False)),
                agy_concurrency,
                openai_concurrency,
                values.get("notes") or None,
                admin_id,
            )
    await audit.record(
        "ai_backend.grant.updated" if previous else "ai_backend.grant.created",
        user_id=user_id,
        data={
            "policy_version": int(row["policy_version"]),
            "agy_enabled": agy_enabled,
            "openai_codex_enabled": openai_enabled,
            "agy_workloads": agy_workloads,
            "openai_codex_workloads": openai_workloads,
            "granted_by": admin_id,
        },
    )
    if previous:
        for backend, enabled, workloads in (
            (ExecutionBackend.AGY, agy_enabled, agy_workloads),
            (ExecutionBackend.OPENAI_CODEX, openai_enabled, openai_workloads),
        ):
            _enabled_key, old_workloads_key, _ = _provider_fields(backend)
            removed = set(previous[old_workloads_key] or []) - set(workloads)
            if not enabled or removed:
                await cancel_revoked_jobs(
                    user_id, removed if enabled else None, backend=backend
                )
    return dict(row)


async def delete_policy(user_id: int, admin_id: int) -> bool:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM user_ai_backend_policies WHERE user_id=$1 RETURNING policy_version;",
            user_id,
        )
    if not row:
        return False
    await audit.record(
        "ai_backend.grant.revoked",
        user_id=user_id,
        data={"previous_policy_version": int(row["policy_version"]), "revoked_by": admin_id},
    )
    await cancel_revoked_jobs(user_id, None, backend=ExecutionBackend.AGY)
    await cancel_revoked_jobs(user_id, None, backend=ExecutionBackend.OPENAI_CODEX)
    return True


async def cancel_revoked_jobs(
    user_id: int,
    removed_workloads: set[str] | None,
    *,
    backend: ExecutionBackend = ExecutionBackend.AGY,
) -> int:
    kinds = []
    if removed_workloads is None or Workload.TRANSLATE_BATCH.value in removed_workloads:
        kinds.append("translate")
    if removed_workloads is None or Workload.CODEX_EXTRACT.value in removed_workloads:
        kinds.append("codex_build")
    if not kinds:
        return 0
    rows = await _deps().revoked_job_ids(user_id, kinds, backend.value)
    changed = 0
    for job_id in rows:
        changed += int(await _deps().cancel_job(job_id))
    return changed
