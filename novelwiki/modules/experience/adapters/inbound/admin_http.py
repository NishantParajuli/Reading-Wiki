"""Admin dashboard endpoints, mounted at /api/admin (every route Depends(require_admin)).

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

from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool
from novelwiki.auth.deps import require_admin
from novelwiki import audit
from novelwiki.ai_backend import policy as backend_policy
from novelwiki.jobs import service as jobs_service
from novelwiki.kernel.errors import InvalidOperation, NotFound, ValidationFailed
from novelwiki.modules.identity.public import IdentityAdminApi, Principal

logger = logging.getLogger(__name__)
router = APIRouter()

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
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT u.id, u.email, u.username, u.display_name, u.avatar_path, u.role, u.status,
                   u.email_verified, u.created_at,
                   u.quota_translated_chapters, u.quota_ocr_pages, u.quota_codex_builds,
                   u.quota_tts_chapters,
                   COALESCE(qz.translated_chapters, 0) AS used_translated,
                   COALESCE(qz.ocr_pages, 0)          AS used_ocr,
                   COALESCE(qz.codex_builds, 0)       AS used_codex,
                   COALESCE(qz.tts_chapters, 0)       AS used_tts,
                   (SELECT COUNT(*) FROM novels n WHERE n.owner_id = u.id) AS novels_owned,
                   p.agy_enabled, p.default_backend, p.agy_workloads, p.fallback_to_api,
                   p.max_concurrent_agy_jobs, p.policy_version, p.notes AS agy_notes,
                   p.updated_at AS agy_updated_at, p.granted_by,
                   (SELECT COUNT(*) FROM jobs j WHERE j.user_id=u.id AND j.execution_backend='agy'
                     AND j.status IN ('queued','running','waiting_provider')) AS agy_active_jobs
            FROM users u
            LEFT JOIN quota_usage qz ON qz.user_id = u.id AND qz.period = $1
            LEFT JOIN user_ai_backend_policies p ON p.user_id=u.id
            WHERE ($2::text IS NULL
                   OR u.email ILIKE '%' || $2 || '%'
                   OR u.username ILIKE '%' || $2 || '%'
                   OR u.display_name ILIKE '%' || $2 || '%')
            ORDER BY u.created_at DESC LIMIT 500;
            """,
            _period(), q,
        )
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
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        exists = await conn.fetchval("SELECT 1 FROM users WHERE id=$1;", user_id)
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
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        heartbeat = await conn.fetchrow(
            "SELECT * FROM ai_worker_heartbeats WHERE backend='agy' ORDER BY heartbeat_at DESC LIMIT 1;"
        )
        counts = await conn.fetchrow(
            """
            SELECT count(*) FILTER (WHERE status='queued') AS queued,
                   count(*) FILTER (WHERE status='running') AS running,
                   count(*) FILTER (WHERE status='waiting_provider') AS waiting,
                   min(created_at) FILTER (WHERE status IN ('queued','waiting_provider')) AS oldest
            FROM jobs WHERE execution_backend='agy';
            """
        )
        recent = await conn.fetch(
            """
            SELECT failure_code,count(*) AS count FROM ai_execution_runs
            WHERE backend='agy' AND failure_code IS NOT NULL AND created_at > now()-interval '7 days'
            GROUP BY failure_code ORDER BY count(*) DESC;
            """
        )
        last_success = await conn.fetchval(
            "SELECT max(finished_at) FROM ai_execution_runs WHERE backend='agy' AND status='completed';"
        )
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
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        recent = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM audit_events WHERE event='agy.smoke.completed' "
            "AND created_at > now()-interval '10 minutes');"
        )
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
    pool = await get_db_pool()
    period = _period()
    async with pool.acquire() as conn:
        totals = await conn.fetchrow(
            """
            SELECT COALESCE(SUM(translated_chapters), 0) AS translated_chapters,
                   COALESCE(SUM(ocr_pages), 0)          AS ocr_pages,
                   COALESCE(SUM(codex_builds), 0)       AS codex_builds,
                   COUNT(DISTINCT user_id)              AS active_users
            FROM quota_usage WHERE period = $1;
            """,
            period,
        )
        user_count = await conn.fetchval("SELECT COUNT(*) FROM users;")
        novel_count = await conn.fetchval("SELECT COUNT(*) FROM novels;")
        months = await conn.fetch(
            """
            SELECT period,
                   SUM(translated_chapters) AS translated_chapters,
                   SUM(ocr_pages) AS ocr_pages,
                   SUM(codex_builds) AS codex_builds
            FROM quota_usage
            WHERE period >= ($1::date - INTERVAL '5 months')
            GROUP BY period ORDER BY period DESC;
            """,
            period,
        )
        top = await conn.fetch(
            """
            SELECT u.id, u.username, u.display_name,
                   qz.translated_chapters, qz.ocr_pages, qz.codex_builds
            FROM quota_usage qz JOIN users u ON u.id = qz.user_id
            WHERE qz.period = $1
            ORDER BY (qz.translated_chapters + qz.ocr_pages + qz.codex_builds) DESC
            LIMIT 10;
            """,
            period,
        )
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
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT n.id, n.title, n.author, n.visibility, n.owner_id, n.updated_at,
                   u.username AS owner_username,
                   (SELECT COUNT(*) FROM chapters c WHERE c.novel_id = n.id) AS chapter_count
            FROM novels n LEFT JOIN users u ON u.id = n.owner_id
            WHERE ($1::text IS NULL OR n.visibility = $1)
              AND ($2::text IS NULL OR n.title ILIKE '%' || $2 || '%')
            ORDER BY n.updated_at DESC NULLS LAST, n.id DESC LIMIT 400;
            """,
            visibility, q,
        )
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
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT n.id, n.title, n.codex_enabled, n.updated_at,
                   (SELECT COUNT(*) FROM chapters c WHERE c.novel_id = n.id) AS chapter_count,
                   (SELECT COUNT(*) FROM sources s WHERE s.novel_id = n.id) AS source_count,
                   COALESCE((SELECT bool_or(s.is_raw) FROM sources s WHERE s.novel_id = n.id), FALSE) AS has_raw,
                   (SELECT MAX(s.last_scraped_at) FROM sources s WHERE s.novel_id = n.id) AS last_scraped_at,
                   (SELECT COUNT(*) FROM chapters c
                      WHERE c.novel_id = n.id AND c.original_text IS NOT NULL AND c.content IS NULL) AS untranslated
            FROM novels n WHERE n.visibility = 'global'
            ORDER BY n.updated_at DESC NULLS LAST, n.id DESC;
            """,
        )
    return [
        {"id": int(r["id"]), "title": r["title"], "codex_enabled": r["codex_enabled"],
         "chapter_count": int(r["chapter_count"] or 0), "source_count": int(r["source_count"] or 0),
         "has_raw": bool(r["has_raw"]), "untranslated": int(r["untranslated"] or 0),
         "last_scraped_at": r["last_scraped_at"].isoformat() if r["last_scraped_at"] else None,
         "updated_at": r["updated_at"].isoformat() if r["updated_at"] else None}
        for r in rows
    ]
