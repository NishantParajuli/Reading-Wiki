"""Admin dashboard endpoints, mounted at /api/admin (every route Depends(require_admin)).
    period = _period()
    totals, user_count, novel_count, months, top = await (
        await _operational_projections()
    ).admin_usage(period)

Tabs the SPA's admin.jsx drives:
  • Users       — list/search, suspend/ban, promote to admin, adjust per-user quotas, delete.
  • Quotas/cost — platform-wide monthly spend totals + top spenders.
  • Moderation  — every novel with owner + visibility (take-down / promote use the shared
                  PATCH /api/novels/{id}/visibility, which already allows admins).

Suspending or banning a user revokes their sessions immediately (the auth dependency also
filters status='active', so they're locked out even before the next request).
"""
import datetime as dt
import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from novelwiki.platform.config import settings
from novelwiki.platform.auth import require_admin
from novelwiki.platform.observability import audit
import novelwiki.modules.ai_execution.public as backend_policy
from novelwiki.modules.work.public import service as jobs_service
from novelwiki.kernel.errors import InvalidOperation, NotFound, ValidationFailed
from novelwiki.modules.identity.public import IdentityAdminApi, Principal

logger = logging.getLogger(__name__)
router = APIRouter()


async def _operational_projections():
    from novelwiki.bootstrap.experience import build_operational_projection_repository
    return await build_operational_projection_repository()

USER_STATUSES = {"active", "suspended", "banned"}
USER_ROLES = {"user", "admin"}
_QUOTA_COLS = ("quota_translated_chapters", "quota_ocr_pages", "quota_codex_builds", "quota_tts_chapters")


async def identity_admin_service_dependency() -> IdentityAdminApi:
    raise RuntimeError("IdentityAdminService was not wired by the composition root")


def _raise_identity_admin_error(exc: Exception) -> None:
    if isinstance(exc, NotFound):
        status = 404
    elif isinstance(exc, InvalidOperation):
        status = 400
    else:
        status = 422
    raise HTTPException(status_code=status, detail=str(exc)) from exc


def _period() -> dt.date:
    return dt.date.today().replace(day=1)


def _limit(value, default: int) -> int:
    return default if value is None else int(value)


class AdminUserUpdate(BaseModel):
    status: str | None = None
    role: str | None = None
    quota_translated_chapters: int | None = None   # null ⇒ reset to settings default
    quota_ocr_pages: int | None = None
    quota_codex_builds: int | None = None
    quota_tts_chapters: int | None = None


class AdminAiBackendPolicy(BaseModel):
    agy_enabled: bool = False
    default_backend: Literal["api", "agy"] = "api"
    agy_workloads: list[str] = Field(default_factory=list)
    fallback_to_api: bool = settings.AGY_FALLBACK_TO_API_DEFAULT
    max_concurrent_agy_jobs: int = Field(default=1, ge=1, le=4)
    notes: str | None = Field(default=None, max_length=1000)


@router.get("/users")
async def admin_list_users(q: str | None = None, admin: dict = Depends(require_admin)):
    """All accounts with this month's usage and effective quota limits."""
    rows = await (await _operational_projections()).admin_users(_period(), q)
    return [
        {
            "id": int(r["id"]), "email": r["email"], "username": r["username"],
            "display_name": r["display_name"], "avatar_url": ("/assets/" + r["avatar_path"]) if r["avatar_path"] else None,
            "role": r["role"], "status": r["status"], "email_verified": r["email_verified"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "novels_owned": int(r["novels_owned"] or 0),
            "usage": {
                "translated_chapters": int(r["used_translated"]),
                "ocr_pages": int(r["used_ocr"]),
                "codex_builds": int(r["used_codex"]),
                "tts_chapters": int(r["used_tts"]),
            },
            "quota_overrides": {
                "translated_chapters": r["quota_translated_chapters"],
                "ocr_pages": r["quota_ocr_pages"],
                "codex_builds": r["quota_codex_builds"],
                "tts_chapters": r["quota_tts_chapters"],
            },
            "limits": {
                "translated_chapters": _limit(r["quota_translated_chapters"], settings.DEFAULT_QUOTA_TRANSLATED_CHAPTERS),
                "ocr_pages": _limit(r["quota_ocr_pages"], settings.DEFAULT_QUOTA_OCR_PAGES),
                "codex_builds": _limit(r["quota_codex_builds"], settings.DEFAULT_QUOTA_CODEX_BUILDS),
                "tts_chapters": _limit(r["quota_tts_chapters"], settings.DEFAULT_QUOTA_TTS_CHAPTERS),
            },
            "ai_backend_policy": {
                "agy_enabled": bool(r["agy_enabled"]),
                "default_backend": r["default_backend"] or "api",
                "agy_workloads": list(r["agy_workloads"] or []),
                "fallback_to_api": bool(r["fallback_to_api"]),
                "max_concurrent_agy_jobs": int(r["max_concurrent_agy_jobs"] or 1),
                "policy_version": int(r["policy_version"]) if r["policy_version"] is not None else None,
                "notes": r["agy_notes"],
                "updated_at": r["agy_updated_at"].isoformat() if r["agy_updated_at"] else None,
                "granted_by": int(r["granted_by"]) if r["granted_by"] is not None else None,
                "active_jobs": int(r["agy_active_jobs"] or 0),
            },
        }
        for r in rows
    ]


@router.patch("/users/{user_id}")
async def admin_update_user(
    user_id: int,
    payload: AdminUserUpdate,
    admin: dict = Depends(require_admin),
    service: IdentityAdminApi = Depends(identity_admin_service_dependency),
):
    """Change a user's status, role, or per-user quota overrides. A null quota value resets
    that meter to the settings default. You can't suspend/ban or demote yourself."""
    try:
        status = await service.update_user(
            user_id,
            payload.model_dump(exclude_unset=True),
            Principal.from_user(admin),
        )
    except (NotFound, InvalidOperation, ValidationFailed) as exc:
        _raise_identity_admin_error(exc)
    return {"status": status}


def _policy_view(row: dict | None, user_id: int) -> dict:
    if not row:
        return {"user_id": user_id, "agy_enabled": False, "default_backend": "api",
                "agy_workloads": [], "fallback_to_api": False,
                "max_concurrent_agy_jobs": 1, "policy_version": None, "notes": None,
                "granted_by": None, "created_at": None, "updated_at": None}
    return {
        "user_id": user_id, "agy_enabled": bool(row["agy_enabled"]),
        "default_backend": row["default_backend"], "agy_workloads": list(row["agy_workloads"] or []),
        "fallback_to_api": bool(row["fallback_to_api"]),
        "max_concurrent_agy_jobs": int(row["max_concurrent_agy_jobs"]),
        "policy_version": int(row["policy_version"]), "notes": row.get("notes"),
        "granted_by": int(row["granted_by"]) if row.get("granted_by") is not None else None,
        "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
        "updated_at": row["updated_at"].isoformat() if row.get("updated_at") else None,
    }


@router.get("/users/{user_id}/ai-backend-policy")
async def admin_get_ai_backend_policy(user_id: int, admin: dict = Depends(require_admin)):
    exists = await (await _operational_projections()).user_exists(user_id)
    if not exists:
        raise HTTPException(status_code=404, detail="User not found.")
    return _policy_view(await backend_policy.get_policy(user_id), user_id)


@router.put("/users/{user_id}/ai-backend-policy")
async def admin_put_ai_backend_policy(user_id: int, payload: AdminAiBackendPolicy,
                                      admin: dict = Depends(require_admin)):
    row = await backend_policy.upsert_policy(user_id, payload.model_dump(), int(admin["id"]))
    return _policy_view(row, user_id)


@router.delete("/users/{user_id}/ai-backend-policy")
async def admin_delete_ai_backend_policy(user_id: int, admin: dict = Depends(require_admin)):
    changed = await backend_policy.delete_policy(user_id, int(admin["id"]))
    return {"status": "revoked" if changed else "noop", "user_id": user_id}


@router.get("/ai/agy/health")
async def admin_agy_health(admin: dict = Depends(require_admin)):
    heartbeat, counts, recent, last_success = await (
        await _operational_projections()
    ).agy_health()
    details = heartbeat["details"] if heartbeat else {}
    if isinstance(details, str):
        try: details = __import__("json").loads(details)
        except Exception: details = {}
    return {
        "enabled": settings.AGY_ENABLED,
        "available": await backend_policy.worker_available(),
        "worker": ({"id": heartbeat["worker_id"], "status": heartbeat["status"],
                    "version": heartbeat["version"], "plugin_version": heartbeat["plugin_version"],
                    "plugin_sha256": heartbeat["plugin_sha256"], "details": details,
                    "heartbeat_at": heartbeat["heartbeat_at"].isoformat()} if heartbeat else None),
        "queue": {"queued": int(counts["queued"] or 0), "running": int(counts["running"] or 0),
                  "waiting_provider": int(counts["waiting"] or 0),
                  "oldest_at": counts["oldest"].isoformat() if counts["oldest"] else None},
        "last_success_at": last_success.isoformat() if last_success else None,
        "recent_failures": [{"code": row["failure_code"], "count": int(row["count"])} for row in recent],
    }


@router.post("/ai/agy/retry-waiting")
async def admin_retry_waiting_agy(admin: dict = Depends(require_admin)):
    count = await jobs_service.retry_waiting()
    await audit.record("agy.run.retry_waiting", user_id=admin["id"], data={"jobs": count})
    return {"status": "success", "jobs_requeued": count}


@router.post("/ai/agy/smoke-test")
async def admin_agy_smoke_test(admin: dict = Depends(require_admin)):
    if not settings.AGY_ENABLED:
        raise HTTPException(status_code=409, detail="Enable AGY before running a consuming smoke test.")
    recent = await (await _operational_projections()).recent_smoke()
    if recent:
        raise HTTPException(status_code=429, detail="An AGY smoke test ran in the last 10 minutes.")
    job_id, created = await jobs_service.create_job(
        "agy_smoke", novel_id=None, user_id=int(admin["id"]), options={},
        idempotency_key="agy-admin-smoke", max_attempts=1,
        backend_requested="agy", execution_backend="agy",
        backend_model=settings.AGY_MODEL_TRANSLATE,
    )
    return {"status": "queued", "job_id": job_id, "deduped": not created,
            "warning": "This explicit smoke test consumes AGY subscription capacity."}


@router.delete("/users/{user_id}")
async def admin_delete_user(
    user_id: int,
    admin: dict = Depends(require_admin),
    service: IdentityAdminApi = Depends(identity_admin_service_dependency),
):
    """Delete a user and cascade their personal data. Their owned novels are kept (owner_id
    is set NULL by the FK). Guards against deleting yourself or the last admin."""
    try:
        await service.delete_user(user_id, Principal.from_user(admin))
    except (NotFound, InvalidOperation, ValidationFailed) as exc:
        _raise_identity_admin_error(exc)
    return {"status": "success"}


@router.get("/usage")
async def admin_usage(admin: dict = Depends(require_admin)):
    """Platform-wide spend: this month's totals, active spender count, the last six months,
    and the top spenders this month."""
    period = _period()
    totals, user_count, novel_count, months, top = await (
        await _operational_projections()
    ).admin_usage(period)
    return {
        "period": period.isoformat(),
        "totals": {
            "translated_chapters": int(totals["translated_chapters"]),
            "ocr_pages": int(totals["ocr_pages"]),
            "codex_builds": int(totals["codex_builds"]),
            "active_users": int(totals["active_users"]),
        },
        "user_count": int(user_count or 0),
        "novel_count": int(novel_count or 0),
        "months": [
            {"period": m["period"].isoformat(),
             "translated_chapters": int(m["translated_chapters"] or 0),
             "ocr_pages": int(m["ocr_pages"] or 0),
             "codex_builds": int(m["codex_builds"] or 0)}
            for m in months
        ],
        "top_spenders": [
            {"id": int(t["id"]), "username": t["username"], "display_name": t["display_name"],
             "translated_chapters": int(t["translated_chapters"]), "ocr_pages": int(t["ocr_pages"]),
             "codex_builds": int(t["codex_builds"])}
            for t in top
        ],
    }


@router.get("/novels")
async def admin_list_novels(visibility: str | None = None, q: str | None = None,
                            admin: dict = Depends(require_admin)):
    """Every novel for moderation: owner, visibility, size. Take-down / promote are done with
    the shared PATCH /api/novels/{id}/visibility (admins may set any visibility)."""
    rows = await (await _operational_projections()).admin_novels(visibility, q)
    return [
        {"id": int(r["id"]), "title": r["title"], "author": r["author"], "visibility": r["visibility"],
         "owner_id": int(r["owner_id"]) if r["owner_id"] is not None else None,
         "owner_username": r["owner_username"], "chapter_count": int(r["chapter_count"] or 0),
         "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None}
        for r in rows
    ]


@router.get("/global-novels")
async def admin_global_novels(admin: dict = Depends(require_admin)):
    """The curated Global library with per-novel pipeline status, for the Global jobs tab.
    The triggers themselves reuse the shared per-novel endpoints (scrape / translate /
    codex/build), which already let an admin act on any novel — this just lists what's there."""
    rows = await (await _operational_projections()).global_novels()
    return [
        {"id": int(r["id"]), "title": r["title"], "codex_enabled": r["codex_enabled"],
         "chapter_count": int(r["chapter_count"] or 0), "source_count": int(r["source_count"] or 0),
         "has_raw": bool(r["has_raw"]), "untranslated": int(r["untranslated"] or 0),
         "last_scraped_at": r["last_scraped_at"].isoformat() if r["last_scraped_at"] else None,
         "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None}
        for r in rows
    ]
