"""Admin-owned AGY grants and server-side backend resolution.

No client value can create an entitlement.  Routes pass a server-owned workload
enum, this module reads the grant row, and the dedicated worker performs the same
authorization again immediately before launching the CLI.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from novelwiki.kernel.errors import Forbidden, NotFound, ProviderUnavailable, RateLimited, ValidationFailed
from novelwiki.platform.observability import audit
from novelwiki.modules.ai_execution.domain.backend import (
    IMPLEMENTED_AGY_WORKLOADS,
    BackendDecision,
    ExecutionBackend,
    RequestedBackend,
    Workload,
    workload_for_job_kind,
)
from novelwiki.platform.config import settings
from novelwiki.platform.database import get_db_pool


class PolicyDependencies(Protocol):
    async def active_job_count(self, user_id: int) -> int: ...
    async def user_exists(self, user_id: int) -> bool: ...
    async def revoked_job_ids(self, user_id: int, kinds: list[str]) -> list[int]: ...
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
        raise ValidationFailed("ai_backend must be auto, api, or agy.") from exc


def model_for(workload: Workload, backend: ExecutionBackend) -> str | None:
    if backend is ExecutionBackend.AGY:
        return {
            Workload.TRANSLATE_BATCH: settings.AGY_MODEL_TRANSLATE,
            Workload.CODEX_EXTRACT: settings.AGY_MODEL_CODEX,
            Workload.SEGMENT_IMPORT: settings.AGY_MODEL_SEGMENT,
            Workload.OCR_PAGES: settings.AGY_MODEL_OCR,
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
            "SELECT * FROM user_ai_backend_policies WHERE user_id=$1;", user_id,
        )
    return dict(row) if row else None


async def worker_available() -> bool:
    """A recent healthy heartbeat is a capability signal, never an entitlement."""
    if not settings.AGY_ENABLED:
        return False
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        return bool(await conn.fetchval(
            """
            SELECT EXISTS(
              SELECT 1 FROM ai_worker_heartbeats
              WHERE backend='agy' AND status='healthy'
                AND heartbeat_at >= now() - $1::interval
            );
            """,
            timedelta(seconds=settings.AGY_WORKER_HEALTH_TTL_SECONDS),
        ))


async def capability_for_user(user_id: int) -> dict:
    policy = await get_policy(user_id)
    enabled = bool(policy and policy.get("agy_enabled"))
    return {
        "agy": {
            "enabled": enabled,
            "default_backend": policy.get("default_backend", "api") if policy else "api",
            "workloads": list(policy.get("agy_workloads") or []) if policy else [],
            "fallback_to_api": bool(policy and policy.get("fallback_to_api")),
            "available": enabled and await worker_available(),
        }
    }


async def _active_agy_count(user_id: int) -> int:
    return await _deps().active_job_count(user_id)


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
        return BackendDecision(req, ExecutionBackend.API, workload, "explicit_api", None, False,
                               model_for(workload, ExecutionBackend.API))

    if not settings.AGY_ENABLED:
        if req is RequestedBackend.AGY:
            raise ProviderUnavailable("Antigravity is temporarily unavailable.")
        return BackendDecision(req, ExecutionBackend.API, workload, "global_disabled", None, False,
                               model_for(workload, ExecutionBackend.API))

    policy = await get_policy(int(user["id"]))
    granted = bool(
        policy
        and policy.get("agy_enabled")
        and workload.value in (policy.get("agy_workloads") or [])
        and workload in IMPLEMENTED_AGY_WORKLOADS
    )
    if not granted:
        if req is RequestedBackend.AGY:
            raise Forbidden("Antigravity is not enabled for this workload.")
        reason = "workload_unimplemented" if workload not in IMPLEMENTED_AGY_WORKLOADS else "not_granted"
        return BackendDecision(req, ExecutionBackend.API, workload, reason, None, False,
                               model_for(workload, ExecutionBackend.API))

    choose_agy = req is RequestedBackend.AGY or policy.get("default_backend") == "agy"
    if not choose_agy:
        return BackendDecision(req, ExecutionBackend.API, workload, "user_policy_default_api",
                               int(policy["policy_version"]), False,
                               model_for(workload, ExecutionBackend.API))

    if user.get("status", "active") != "active":
        raise Forbidden("This account cannot schedule AI work.")
    if enforce_concurrency:
        active = await _active_agy_count(int(user["id"]))
        if active >= int(policy.get("max_concurrent_agy_jobs") or 1):
            raise RateLimited("Your Antigravity queue limit is already in use.")

    return BackendDecision(
        req,
        ExecutionBackend.AGY,
        workload,
        "explicit_agy" if req is RequestedBackend.AGY else "user_policy_default",
        int(policy["policy_version"]),
        bool(policy.get("fallback_to_api")),
        model_for(workload, ExecutionBackend.AGY),
    )


async def reauthorize_job(job: dict, user: dict) -> tuple[bool, str]:
    """Recheck current grant/status just before an AGY subprocess starts."""
    if not settings.AGY_ENABLED:
        return False, "global_disabled"
    if not user or user.get("status") != "active":
        return False, "user_inactive"
    workload = workload_for_job_kind(job.get("kind", ""))
    if workload is None or workload not in IMPLEMENTED_AGY_WORKLOADS:
        return False, "workload_unimplemented"
    policy = await get_policy(int(user["id"]))
    if not policy or not policy.get("agy_enabled"):
        return False, "grant_revoked"
    if workload.value not in (policy.get("agy_workloads") or []):
        return False, "workload_revoked"
    return True, "policy_version_changed" if int(policy["policy_version"]) != int(job.get("backend_policy_version") or 0) else "ok"


async def upsert_policy(user_id: int, values: dict, admin_id: int) -> dict:
    workloads = sorted(set(values.get("agy_workloads") or []))
    unknown = set(workloads) - {w.value for w in Workload}
    if unknown:
        raise ValidationFailed(f"Unknown AGY workload(s): {', '.join(sorted(unknown))}.")
    enabled = bool(values.get("agy_enabled", False))
    default = values.get("default_backend", "api")
    if default not in ("api", "agy") or (default == "agy" and not enabled):
        raise ValidationFailed("AGY can be the default only while AGY access is enabled.")
    concurrency = int(values.get("max_concurrent_agy_jobs", 1))
    if not 1 <= concurrency <= 4:
        raise ValidationFailed("max_concurrent_agy_jobs must be between 1 and 4.")

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            exists = await _deps().user_exists(user_id)
            if not exists:
                raise NotFound("User not found.")
            previous = await conn.fetchrow(
                "SELECT * FROM user_ai_backend_policies WHERE user_id=$1 FOR UPDATE;", user_id,
            )
            row = await conn.fetchrow(
                """
                INSERT INTO user_ai_backend_policies
                  (user_id, agy_enabled, default_backend, agy_workloads, fallback_to_api,
                   max_concurrent_agy_jobs, notes, granted_by)
                VALUES ($1,$2,$3,$4::text[],$5,$6,$7,$8)
                ON CONFLICT (user_id) DO UPDATE SET
                  agy_enabled=EXCLUDED.agy_enabled,
                  default_backend=EXCLUDED.default_backend,
                  agy_workloads=EXCLUDED.agy_workloads,
                  fallback_to_api=EXCLUDED.fallback_to_api,
                  max_concurrent_agy_jobs=EXCLUDED.max_concurrent_agy_jobs,
                  notes=EXCLUDED.notes,
                  granted_by=EXCLUDED.granted_by,
                  policy_version=user_ai_backend_policies.policy_version + 1,
                  updated_at=now()
                RETURNING *;
                """,
                user_id, enabled, default, workloads, bool(values.get("fallback_to_api", False)),
                concurrency, (values.get("notes") or None), admin_id,
            )
    event = "agy.grant.updated" if previous else "agy.grant.created"
    await audit.record(event, user_id=user_id, data={
        "policy_version": int(row["policy_version"]), "enabled": enabled,
        "workloads": workloads, "granted_by": admin_id,
    })
    if previous:
        removed = set(previous["agy_workloads"] or []) - set(workloads)
        if not enabled or removed:
            await cancel_revoked_jobs(user_id, removed if enabled else None)
    return dict(row)


async def delete_policy(user_id: int, admin_id: int) -> bool:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "DELETE FROM user_ai_backend_policies WHERE user_id=$1 RETURNING policy_version;", user_id,
        )
    if not row:
        return False
    await audit.record("agy.grant.revoked", user_id=user_id,
                       data={"previous_policy_version": int(row["policy_version"]), "revoked_by": admin_id})
    await cancel_revoked_jobs(user_id, None)
    return True


async def cancel_revoked_jobs(user_id: int, removed_workloads: set[str] | None) -> int:
    kinds = []
    if removed_workloads is None or Workload.TRANSLATE_BATCH.value in removed_workloads:
        kinds.append("translate")
    if removed_workloads is None or Workload.CODEX_EXTRACT.value in removed_workloads:
        kinds.append("codex_build")
    if not kinds:
        return 0
    rows = await _deps().revoked_job_ids(user_id, kinds)
    changed = 0
    for job_id in rows:
        changed += int(await _deps().cancel_job(job_id))
    return changed
