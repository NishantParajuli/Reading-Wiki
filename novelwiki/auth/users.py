"""User serialization, quota resolution, and username helpers."""
import json

from novelwiki.config.settings import settings
from novelwiki.modules.identity.domain.policies import normalize_username, valid_username


def _prefs(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw:
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return {}
    return {}


def avatar_url(user: dict) -> str | None:
    """The public /assets/_users URL for a user's avatar, or None."""
    p = user.get("avatar_path")
    return ("/assets/" + p) if p else None


def quota_limits(user: dict) -> dict:
    """Effective monthly limits: the per-user override if set, else the settings default."""
    def limit(key: str, default: int) -> int:
        value = user.get(key)
        return default if value is None else int(value)

    return {
        "translated_chapters": limit("quota_translated_chapters", settings.DEFAULT_QUOTA_TRANSLATED_CHAPTERS),
        "ocr_pages": limit("quota_ocr_pages", settings.DEFAULT_QUOTA_OCR_PAGES),
        "codex_builds": limit("quota_codex_builds", settings.DEFAULT_QUOTA_CODEX_BUILDS),
        "tts_chapters": limit("quota_tts_chapters", settings.DEFAULT_QUOTA_TTS_CHAPTERS),
    }


def self_user(user: dict) -> dict:
    """Full projection for the account owner (GET /api/auth/me)."""
    return {
        "id": int(user["id"]),
        "email": user["email"],
        "email_verified": bool(user["email_verified"]),
        "username": user["username"],
        "display_name": user.get("display_name"),
        "bio": user.get("bio"),
        "avatar_path": user.get("avatar_path"),
        "avatar_url": avatar_url(user),
        "role": user.get("role", "user"),
        "prefs": _prefs(user.get("prefs")),
        "quota_limits": quota_limits(user),
    }


async def self_user_with_capabilities(user: dict) -> dict:
    """Owner projection plus server-owned backend entitlement and worker health."""
    from novelwiki.ai_backend.policy import capability_for_user

    result = self_user(user)
    result["ai_backends"] = await capability_for_user(int(user["id"]))
    return result


def public_user(user: dict) -> dict:
    """Projection visible to other users on a profile page (no email/role/quota)."""
    return {
        "id": int(user["id"]),
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "bio": user.get("bio"),
        "avatar_path": user.get("avatar_path"),
        "avatar_url": avatar_url(user),
        "created_at": user["created_at"].isoformat() if user.get("created_at") else None,
    }


async def unique_username(conn, base: str) -> str:
    """Return `base` (normalized) or `base_N` for the first free slot."""
    base = normalize_username(base)
    if not await conn.fetchval("SELECT 1 FROM users WHERE username = $1;", base):
        return base
    for n in range(2, 10000):
        candidate = f"{base[:20]}_{n}"
        if not await conn.fetchval("SELECT 1 FROM users WHERE username = $1;", candidate):
            return candidate
    # Fall back to something certainly unique.
    return normalize_username(base) + "_" + base[:4]
