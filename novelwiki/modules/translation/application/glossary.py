from __future__ import annotations

from collections.abc import Callable

from novelwiki.kernel.transactions import UnitOfWork
from novelwiki.modules.catalog.public import CatalogTransactionApi
from novelwiki.modules.codex.public import EstablishedTermsApi
from novelwiki.modules.identity.public import Principal
from novelwiki.modules.translation.public import GlossaryTerm, TranslationTransactionApi


class GlossaryService:
    def __init__(self, uow_factory: Callable[[], UnitOfWork]):
        self._uow_factory = uow_factory

    async def seed(self, novel_id: int, principal: Principal) -> int:
        async with self._uow_factory() as uow:
            catalog = uow.transaction.bind(CatalogTransactionApi)
            await catalog.require_editable(novel_id, principal)
            terms = await uow.transaction.bind(EstablishedTermsApi).list_established_terms(
                novel_id
            )
            return await uow.transaction.bind(
                TranslationTransactionApi
            ).seed_established_terms(novel_id, terms)

    async def list(self, novel_id: int, principal: Principal) -> list[GlossaryTerm]:
        async with self._uow_factory() as uow:
            await uow.transaction.bind(CatalogTransactionApi).require_readable(
                novel_id, principal
            )
            return await uow.transaction.bind(TranslationTransactionApi).list_glossary(
                novel_id
            )

    async def upsert(
        self, novel_id: int, principal: Principal, *, source_term: str,
        translation: str, term_type: str | None, notes: str | None, locked: bool,
    ) -> int:
        async with self._uow_factory() as uow:
            await uow.transaction.bind(CatalogTransactionApi).require_editable(
                novel_id, principal
            )
            return await uow.transaction.bind(TranslationTransactionApi).upsert_glossary(
                novel_id, source_term, translation, term_type, notes, locked
            )

    async def delete(self, novel_id: int, term_id: int, principal: Principal) -> None:
        async with self._uow_factory() as uow:
            await uow.transaction.bind(CatalogTransactionApi).require_editable(
                novel_id, principal
            )
            await uow.transaction.bind(TranslationTransactionApi).delete_glossary(
                novel_id, term_id
            )
