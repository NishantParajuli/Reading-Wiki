from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from novelwiki.kernel.transactions import UnitOfWork
from novelwiki.modules.codex.public import CodexExtractionTransactionApi
from novelwiki.modules.reading.public import ReadingCodexTransactionApi


async def commit_codex_extraction(
    uow_factory: Callable[[], UnitOfWork],
    novel_id: int,
    chapter: float,
    data: dict,
    running_summary: str,
    *,
    expected_source_hash: str,
    resolved_refs: dict[str, int | None],
    roster_refs: dict[str, int] | None = None,
    run_id: Any | None = None,
    model_label: str | None = None,
    force: bool = False,
) -> dict:
    """Atomically verify Reading source bytes and commit Codex-owned artifacts."""
    async with uow_factory() as uow:
        reading = uow.transaction.bind(ReadingCodexTransactionApi)
        source = await reading.locked_chapter_snapshot(novel_id, chapter)
        actual_hash = hashlib.sha256(
            ((source or {}).get("content") or "").encode("utf-8")
        ).hexdigest()
        if source is None or actual_hash != expected_source_hash:
            raise RuntimeError("source_changed")
        codex = uow.transaction.bind(CodexExtractionTransactionApi)
        return await codex.commit_extraction(
            novel_id,
            chapter,
            data,
            running_summary,
            chapter_snapshot=source,
            expected_source_hash=expected_source_hash,
            resolved_refs=resolved_refs,
            roster_refs=dict(roster_refs or {}),
            run_id=run_id,
            model_label=model_label,
            force=force,
        )
