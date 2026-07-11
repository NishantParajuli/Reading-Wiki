from __future__ import annotations

from dataclasses import replace

from novelwiki.platform.config import settings

from ..public import Principal


def principal_from_user(user: dict) -> Principal:
    def limit(column: str, default: int) -> int:
        value = user.get(column)
        return default if value is None else int(value)

    return replace(
        Principal.from_user(user),
        quota_limits={
            "translated_chapters": limit(
                "quota_translated_chapters",
                settings.DEFAULT_QUOTA_TRANSLATED_CHAPTERS,
            ),
            "ocr_pages": limit("quota_ocr_pages", settings.DEFAULT_QUOTA_OCR_PAGES),
            "codex_builds": limit(
                "quota_codex_builds", settings.DEFAULT_QUOTA_CODEX_BUILDS
            ),
            "tts_chapters": limit(
                "quota_tts_chapters", settings.DEFAULT_QUOTA_TTS_CHAPTERS
            ),
        },
    )
