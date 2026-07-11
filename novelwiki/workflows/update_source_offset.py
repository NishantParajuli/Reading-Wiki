from __future__ import annotations

from collections.abc import Callable

from novelwiki.kernel.transactions import UnitOfWork
from novelwiki.modules.acquisition.public import AcquisitionTransactionApi
from novelwiki.modules.codex.public import CodexTransactionApi
from novelwiki.modules.reading.public import ReadingTransactionApi


async def update_source_offset(
    uow_factory: Callable[[], UnitOfWork], source_id: int, new_offset: float
) -> int:
    """Renumber an Acquisition source and all owner-managed chapter references atomically."""
    async with uow_factory() as uow:
        acquisition = uow.transaction.bind(AcquisitionTransactionApi)
        reading = uow.transaction.bind(ReadingTransactionApi)
        codex = uow.transaction.bind(CodexTransactionApi)
        novel_id, old_offset = await acquisition.source_offset_state(source_id)
        chapters = await reading.source_chapter_numbers(source_id)
        delta = float(new_offset) - old_offset
        if delta and await codex.has_chapter_artifacts(novel_id, chapters):
            raise ValueError(
                "This source has codex artifacts built on its current chapter numbering; "
                "clear/rebuild the codex before changing the offset."
            )
        renumbered = await reading.renumber_source_chapters(source_id, novel_id, delta)
        await acquisition.set_source_offset(source_id, float(new_offset))
    return renumbered
