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

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool
from novelwiki.auth.deps import require_admin
from novelwiki.auth.sessions import revoke_user_sessions

logger = logging.getLogger(__name__)
router = APIRouter()

USER_STATUSES = {"active", "suspended", "banned"}
USER_ROLES = {"user", "admin"}
_QUOTA_COLS = ("quota_translated_chapters", "quota_ocr_pages", "quota_codex_builds")


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
                   COALESCE(qz.translated_chapters, 0) AS used_translated,
                   COALESCE(qz.ocr_pages, 0)          AS used_ocr,
                   COALESCE(qz.codex_builds, 0)       AS used_codex,
                   (SELECT COUNT(*) FROM novels n WHERE n.owner_id = u.id) AS novels_owned
            FROM users u
            LEFT JOIN quota_usage qz ON qz.user_id = u.id AND qz.period = $1
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
            },
            "quota_overrides": {
                "translated_chapters": r["quota_translated_chapters"],
                "ocr_pages": r["quota_ocr_pages"],
                "codex_builds": r["quota_codex_builds"],
            },
            "limits": {
                "translated_chapters": _limit(r["quota_translated_chapters"], settings.DEFAULT_QUOTA_TRANSLATED_CHAPTERS),
                "ocr_pages": _limit(r["quota_ocr_pages"], settings.DEFAULT_QUOTA_OCR_PAGES),
                "codex_builds": _limit(r["quota_codex_builds"], settings.DEFAULT_QUOTA_CODEX_BUILDS),
            },
        }
        for r in rows
    ]


@router.patch("/users/{user_id}")
async def admin_update_user(user_id: int, payload: AdminUserUpdate, admin: dict = Depends(require_admin)):
    """Change a user's status, role, or per-user quota overrides. A null quota value resets
    that meter to the settings default. You can't suspend/ban or demote yourself."""
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        return {"status": "noop"}
    if "status" in fields and fields["status"] not in USER_STATUSES:
        raise HTTPException(status_code=422, detail=f"status must be one of {sorted(USER_STATUSES)}.")
    if "role" in fields and fields["role"] not in USER_ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {sorted(USER_ROLES)}.")
    if user_id == admin["id"] and (
        ("status" in fields and fields["status"] != "active") or fields.get("role") == "user"
    ):
        raise HTTPException(status_code=400, detail="You can't suspend or demote your own admin account.")

    sets, args = [], []
    for key in ("status", "role", *_QUOTA_COLS):
        if key in fields:
            args.append(fields[key])
            sets.append(f"{key} = ${len(args)}")
    if not sets:
        return {"status": "noop"}

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        target = await conn.fetchrow("SELECT id, role FROM users WHERE id = $1;", user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found.")
        # Don't strip the last admin.
        if target["role"] == "admin" and fields.get("role") == "user":
            others = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'admin' AND id <> $1;", user_id)
            if not others:
                raise HTTPException(status_code=400, detail="This is the only admin — promote someone else first.")
        args.append(user_id)
        await conn.execute(
            f"UPDATE users SET {', '.join(sets)}, updated_at = now() WHERE id = ${len(args)};", *args,
        )
        # Suspending/banning takes effect now: kill their sessions.
        if fields.get("status") in ("suspended", "banned"):
            await revoke_user_sessions(conn, user_id)
    return {"status": "success"}


@router.delete("/users/{user_id}")
async def admin_delete_user(user_id: int, admin: dict = Depends(require_admin)):
    """Delete a user and cascade their personal data. Their owned novels are kept (owner_id
    is set NULL by the FK). Guards against deleting yourself or the last admin."""
    if user_id == admin["id"]:
        raise HTTPException(status_code=400, detail="You can't delete your own account here.")
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        target = await conn.fetchrow("SELECT id, role FROM users WHERE id = $1;", user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found.")
        if target["role"] == "admin":
            others = await conn.fetchval("SELECT COUNT(*) FROM users WHERE role = 'admin' AND id <> $1;", user_id)
            if not others:
                raise HTTPException(status_code=400, detail="Can't delete the only admin.")
        await conn.execute("DELETE FROM users WHERE id = $1;", user_id)
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
