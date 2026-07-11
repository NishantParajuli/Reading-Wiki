from __future__ import annotations

from novelwiki.modules.translation.public import GlossaryTerm


class PostgresTranslationTransactionService:
    def __init__(self, connection):
        self._connection = connection

    async def list_glossary(self, novel_id: int) -> list[GlossaryTerm]:
        rows = await self._connection.fetch(
            """
            SELECT id, source_term, translation, term_type, notes, locked
            FROM translation_glossary WHERE novel_id = $1
            ORDER BY locked DESC, term_type NULLS LAST, source_term ASC;
            """,
            novel_id,
        )
        return [
            GlossaryTerm(
                id=int(row["id"]), source_term=row["source_term"],
                translation=row["translation"], term_type=row["term_type"],
                notes=row["notes"], locked=bool(row["locked"]),
            )
            for row in rows
        ]

    async def upsert_glossary(
        self, novel_id: int, source_term: str, translation: str,
        term_type: str | None, notes: str | None, locked: bool,
    ) -> int:
        return int(await self._connection.fetchval(
            """
            INSERT INTO translation_glossary
              (novel_id, source_term, translation, term_type, notes, locked)
            VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (novel_id, source_term) DO UPDATE
            SET translation = EXCLUDED.translation, term_type = EXCLUDED.term_type,
                notes = EXCLUDED.notes, locked = EXCLUDED.locked
            RETURNING id;
            """,
            novel_id, source_term.strip(), translation.strip(), term_type, notes, locked,
        ))

    async def delete_glossary(self, novel_id: int, term_id: int) -> None:
        await self._connection.execute(
            "DELETE FROM translation_glossary WHERE id = $1 AND novel_id = $2;",
            term_id, novel_id,
        )

    async def seed_established_terms(self, novel_id: int, terms: list[object]) -> int:
        type_map = {
            "character": "name", "location": "place", "faction": "name",
            "organization": "name", "item": "item",
        }
        seeded = 0
        for term in terms:
            name = (term.canonical_name or "").strip()
            if not name:
                continue
            result = await self._connection.execute(
                """
                INSERT INTO translation_glossary
                  (novel_id, source_term, translation, term_type, notes)
                VALUES ($1, $2, $2, $3, 'seeded from codex')
                ON CONFLICT (novel_id, source_term) DO NOTHING;
                """,
                novel_id, name, type_map.get(term.entity_type, "term"),
            )
            if result.endswith("1"):
                seeded += 1
        return seeded
