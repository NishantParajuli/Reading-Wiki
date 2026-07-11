from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from novelwiki.kernel.transactions import UnitOfWork
from novelwiki.modules.acquisition.public import AcquisitionTransactionApi
from novelwiki.modules.catalog.public import CatalogTransactionApi
from novelwiki.modules.codex.public import CodexTransactionApi
from novelwiki.modules.reading.public import ReadingIngestionTransactionApi


@dataclass(frozen=True)
class ImportCommitApis:
    acquisition: AcquisitionTransactionApi
    catalog: CatalogTransactionApi
    reading: ReadingIngestionTransactionApi
    codex: CodexTransactionApi


async def commit_import(
    uow_factory: Callable[[], UnitOfWork],
    operation: Callable[[ImportCommitApis], Awaitable[dict]],
) -> dict:
    """Run a prepared import commit through transaction-bound owner capabilities."""
    async with uow_factory() as uow:
        return await operation(ImportCommitApis(
            acquisition=uow.transaction.bind(AcquisitionTransactionApi),
            catalog=uow.transaction.bind(CatalogTransactionApi),
            reading=uow.transaction.bind(ReadingIngestionTransactionApi),
            codex=uow.transaction.bind(CodexTransactionApi),
        ))
