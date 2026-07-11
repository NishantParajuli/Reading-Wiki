from __future__ import annotations

from novelwiki.platform.config import settings

from ..public import Principal


def principal_from_user(user: dict) -> Principal:
    return Principal.from_user(
        user,
        {
            "translated_chapters": settings.DEFAULT_QUOTA_TRANSLATED_CHAPTERS,
            "ocr_pages": settings.DEFAULT_QUOTA_OCR_PAGES,
            "codex_builds": settings.DEFAULT_QUOTA_CODEX_BUILDS,
            "tts_chapters": settings.DEFAULT_QUOTA_TTS_CHAPTERS,
        },
    )
