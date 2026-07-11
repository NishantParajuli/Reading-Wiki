from __future__ import annotations

from novelwiki.modules.codex.public import EstablishedTerm


class PostgresEstablishedTerms:
    def __init__(self, connection):
        self._connection = connection

    async def list_established_terms(self, novel_id: int) -> list[EstablishedTerm]:
        rows = await self._connection.fetch(
            """
            SELECT canonical_name, type FROM entities
            WHERE novel_id = $1
              AND type IN ('character', 'location', 'faction', 'organization', 'item')
            ORDER BY first_seen_chapter ASC;
            """,
            novel_id,
        )
        return [
            EstablishedTerm(row["canonical_name"], row["type"])
            for row in rows
        ]
