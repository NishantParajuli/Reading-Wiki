from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class GlossaryTerm:
    id: int
    source_term: str
    translation: str
    term_type: str | None
    notes: str | None
    locked: bool


class TranslationTransactionApi(Protocol):
    async def list_glossary(self, novel_id: int) -> list[GlossaryTerm]: ...
    async def upsert_glossary(
        self, novel_id: int, source_term: str, translation: str,
        term_type: str | None, notes: str | None, locked: bool,
    ) -> int: ...
    async def delete_glossary(self, novel_id: int, term_id: int) -> None: ...
    async def seed_established_terms(self, novel_id: int, terms: list[object]) -> int: ...


class TranslationApi(Protocol):
    async def translate_chapter(self, novel_id: int, chapter: float, user_id: int) -> object: ...
    async def translate_raw_text(self, text: str, novel_id: int | None = None) -> str: ...
