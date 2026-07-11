from __future__ import annotations

from collections.abc import Callable
from typing import Any

from novelwiki.kernel.transactions import UnitOfWork
from novelwiki.modules.reading.public import ReadingTranslationTransactionApi
from novelwiki.modules.translation.public import TranslationTransactionApi
from novelwiki.modules.work.public import WorkTransactionApi


async def commit_translation(
    uow_factory: Callable[[], UnitOfWork], novel_id: int, chapter: float, *,
    expected_source_hash: str, expected_content_version: int,
    translated_title: str | None, translation: str, new_terms: list[dict],
    model_label: str, run_id: Any | None = None, job_id: int | None = None,
) -> dict:
    """Commit Reading content, Translation terms, and Work consumption atomically."""
    async with uow_factory() as uow:
        reading = uow.transaction.bind(ReadingTranslationTransactionApi)
        result = await reading.commit_translation(
            novel_id, chapter, expected_source_hash=expected_source_hash,
            expected_content_version=expected_content_version,
            translated_title=translated_title, translation=translation,
            model_label=model_label, run_id=run_id,
        )
        if result.get("idempotent"):
            return result
        translation_api = uow.transaction.bind(TranslationTransactionApi)
        await translation_api.insert_discovered_terms(novel_id, new_terms)
        if job_id is not None:
            work = uow.transaction.bind(WorkTransactionApi)
            await work.increment_quota_consumed(job_id, 1)
    return {**result, "new_terms": len(new_terms)}
