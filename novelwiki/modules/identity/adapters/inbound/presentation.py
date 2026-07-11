"""Identity-owned response projections."""
from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from novelwiki.platform.config import settings


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
    path = user.get("avatar_path")
    return ("/assets/" + path) if path else None


def quota_limits(user: dict) -> dict:
    def limit(key: str, default: int) -> int:
        value = user.get(key)
        return default if value is None else int(value)

    return {
        "translated_chapters": limit(
            "quota_translated_chapters", settings.DEFAULT_QUOTA_TRANSLATED_CHAPTERS
        ),
        "ocr_pages": limit("quota_ocr_pages", settings.DEFAULT_QUOTA_OCR_PAGES),
        "codex_builds": limit("quota_codex_builds", settings.DEFAULT_QUOTA_CODEX_BUILDS),
        "tts_chapters": limit("quota_tts_chapters", settings.DEFAULT_QUOTA_TTS_CHAPTERS),
    }


def self_user(user: dict) -> dict:
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


async def self_user_with_capabilities(
    user: dict,
    capability_for_user: Callable[[int], Awaitable[dict]],
) -> dict:
    result = self_user(user)
    result["ai_backends"] = await capability_for_user(int(user["id"]))
    return result


def public_user(user: dict) -> dict:
    return {
        "id": int(user["id"]),
        "username": user["username"],
        "display_name": user.get("display_name") or user["username"],
        "bio": user.get("bio"),
        "avatar_path": user.get("avatar_path"),
        "avatar_url": avatar_url(user),
        "created_at": user["created_at"].isoformat() if user.get("created_at") else None,
    }
