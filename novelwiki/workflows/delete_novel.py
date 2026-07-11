from __future__ import annotations

from collections.abc import Callable

from novelwiki.kernel.transactions import UnitOfWork
from novelwiki.modules.acquisition.public import AcquisitionTransactionApi
from novelwiki.modules.catalog.public import CatalogTransactionApi
from novelwiki.modules.identity.public import Principal


async def delete_novel(
    uow_factory: Callable[[], UnitOfWork], principal: Principal, novel_id: int
) -> list[int]:
    """Collect cleanup targets and delete the Catalog root in one DB transaction."""
    async with uow_factory() as uow:
        catalog = uow.transaction.bind(CatalogTransactionApi)
        await catalog.require_editable(novel_id, principal)
        acquisition = uow.transaction.bind(AcquisitionTransactionApi)
        import_job_ids = await acquisition.list_import_job_ids(novel_id)
        await catalog.delete_novel(novel_id)
    return import_job_ids
