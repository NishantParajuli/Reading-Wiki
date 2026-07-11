from __future__ import annotations

from collections.abc import Callable

from novelwiki.kernel.transactions import UnitOfWork
from novelwiki.modules.acquisition.public import AcquisitionTransactionApi, SourceDraft
from novelwiki.modules.catalog.public import CatalogTransactionApi, NovelDraft
from novelwiki.modules.identity.public import Principal


async def create_novel_with_source(
    uow_factory: Callable[[], UnitOfWork],
    principal: Principal,
    novel: NovelDraft,
    source: SourceDraft | None,
) -> tuple[int, int | None]:
    """Create the Catalog aggregate and optional Acquisition source atomically."""
    async with uow_factory() as uow:
        catalog = uow.transaction.bind(CatalogTransactionApi)
        novel_id = await catalog.create_novel(novel, principal.user_id)
        await catalog.add_to_library(novel_id, principal.user_id)
        source_id = None
        if source is not None:
            acquisition = uow.transaction.bind(AcquisitionTransactionApi)
            source_id = await acquisition.create_source(novel_id, source)
    return novel_id, source_id
