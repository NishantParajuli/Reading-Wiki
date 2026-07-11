from __future__ import annotations

from typing import Any

from ...public import ImportedNovelDraft, NovelAccess, NovelDraft, TagSuggestionRecord


class PostgresCatalogRepository:
    def __init__(self, connection: Any):
        self._connection = connection

    async def get_access(self, novel_id: int) -> NovelAccess | None:
        row = await self._connection.fetchrow(
            "SELECT id, owner_id, visibility, contribution_policy, title, description "
            "FROM novels WHERE id = $1;",
            novel_id,
        )
        if row is None:
            return None
        return NovelAccess(
            novel_id=int(row["id"]),
            owner_id=int(row["owner_id"]) if row["owner_id"] is not None else None,
            visibility=row["visibility"],
            contribution_policy=row["contribution_policy"],
            title=row["title"],
            description=row["description"],
        )

    async def add_to_library(self, novel_id: int, user_id: int) -> None:
        await self._connection.execute(
            "INSERT INTO library_entries (user_id, novel_id) VALUES ($1, $2) "
            "ON CONFLICT (user_id, novel_id) DO NOTHING;",
            user_id,
            novel_id,
        )

    async def remove_from_library(self, novel_id: int, user_id: int) -> None:
        await self._connection.execute(
            "DELETE FROM library_entries WHERE user_id = $1 AND novel_id = $2;",
            user_id,
            novel_id,
        )

    async def set_visibility(
        self, novel_id: int, visibility: str, steward_id: int | None = None
    ) -> None:
        if visibility == "global":
            await self._connection.execute(
                "UPDATE novels SET visibility = 'global', owner_id = $2, updated_at = now() "
                "WHERE id = $1;",
                novel_id,
                steward_id,
            )
        else:
            await self._connection.execute(
                "UPDATE novels SET visibility = $2, updated_at = now() WHERE id = $1;",
                novel_id,
                visibility,
            )

    async def set_shelf(
        self, novel_id: int, user_id: int, shelf: str | None
    ) -> None:
        await self._connection.execute(
            """
            INSERT INTO library_entries (user_id, novel_id, shelf)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id, novel_id) DO UPDATE SET shelf = EXCLUDED.shelf;
            """,
            user_id,
            novel_id,
            shelf,
        )

    async def update_metadata(self, novel_id: int, fields: dict) -> None:
        allowed = {
            "title", "author", "description", "cover_url", "codex_enabled",
            "status_tags", "contribution_policy",
        }
        if not set(fields) <= allowed:
            raise ValueError("unsupported catalog metadata field")
        sets: list[str] = []
        arguments: list[object] = []
        for key, value in fields.items():
            arguments.append(value)
            sets.append(f"{key} = ${len(arguments)}")
        arguments.append(novel_id)
        await self._connection.execute(
            f"UPDATE novels SET {', '.join(sets)}, updated_at = now() "
            f"WHERE id = ${len(arguments)};",
            *arguments,
        )

    async def create_novel(self, draft: NovelDraft, owner_id: int | None) -> int:
        return int(await self._connection.fetchval(
            """
            INSERT INTO novels (title, author, description, cover_url, original_language,
                                codex_enabled, owner_id, visibility)
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'private') RETURNING id;
            """,
            draft.title, draft.author, draft.description, draft.cover_url,
            draft.original_language, draft.codex_enabled, owner_id,
        ))

    async def create_imported_novel(self, draft: ImportedNovelDraft) -> int:
        return int(await self._connection.fetchval(
            """
            INSERT INTO novels
              (title,author,description,original_language,codex_enabled,series,
               owner_id,visibility)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8) RETURNING id;
            """,
            draft.title, draft.author, draft.description, draft.original_language,
            draft.codex_enabled, draft.series, draft.owner_id, draft.visibility,
        ))

    async def novel_exists(self, novel_id: int) -> bool:
        return bool(await self._connection.fetchval(
            "SELECT 1 FROM novels WHERE id=$1;", novel_id
        ))

    async def codex_enabled(self, novel_id: int) -> bool:
        return bool(await self._connection.fetchval(
            "SELECT codex_enabled FROM novels WHERE id=$1;", novel_id
        ))

    async def set_cover_if_missing(self, novel_id: int, cover_url: str) -> None:
        await self._connection.execute(
            "UPDATE novels SET cover_url=$2,updated_at=now() "
            "WHERE id=$1 AND cover_url IS NULL;", novel_id, cover_url,
        )

    async def touch_novel(self, novel_id: int) -> None:
        await self._connection.execute(
            "UPDATE novels SET updated_at=now() WHERE id=$1;", novel_id
        )

    async def novel_titles(self, novel_ids: set[int]) -> dict[int, str]:
        if not novel_ids:
            return {}
        rows = await self._connection.fetch(
            "SELECT id,title FROM novels WHERE id=ANY($1::bigint[]);", sorted(novel_ids)
        )
        return {int(row["id"]): row["title"] for row in rows}

    async def delete_novel(self, novel_id: int) -> None:
        await self._connection.execute("DELETE FROM novels WHERE id = $1;", novel_id)

    async def create_tag_suggestion(
        self, novel_id: int, from_user_id: int, tags: list[str], note: str | None
    ) -> int:
        return int(await self._connection.fetchval(
            """
            INSERT INTO tag_suggestions (novel_id, from_user_id, tags, note)
            VALUES ($1, $2, $3, $4) RETURNING id;
            """,
            novel_id, from_user_id, tags, note,
        ))

    async def list_tag_suggestions(
        self, novel_id: int, status: str
    ) -> list[TagSuggestionRecord]:
        rows = await self._connection.fetch(
            """
            SELECT id, from_user_id, tags, note, status, created_at
            FROM tag_suggestions
            WHERE novel_id = $1 AND ($2 = 'all' OR status = $2)
            ORDER BY created_at DESC LIMIT 200;
            """,
            novel_id, status,
        )
        return [
            TagSuggestionRecord(
                id=int(row["id"]), from_user_id=int(row["from_user_id"]),
                tags=tuple(row["tags"] or ()), note=row["note"],
                status=row["status"], created_at=row["created_at"],
            )
            for row in rows
        ]

    async def get_tag_suggestion(
        self, novel_id: int, suggestion_id: int
    ) -> tuple[list[str], str] | None:
        row = await self._connection.fetchrow(
            "SELECT tags, status FROM tag_suggestions WHERE id = $1 AND novel_id = $2;",
            suggestion_id, novel_id,
        )
        if row is None:
            return None
        return list(row["tags"] or []), str(row["status"])

    async def apply_tags(self, novel_id: int, tags: list[str]) -> None:
        await self._connection.execute(
            "UPDATE novels SET status_tags = $2, updated_at = now() WHERE id = $1;",
            novel_id, tags,
        )

    async def review_tag_suggestion(
        self, suggestion_id: int, status: str, reviewed_by: int
    ) -> bool:
        updated = await self._connection.fetchval(
            "UPDATE tag_suggestions SET status = $2, reviewed_by = $3, reviewed_at = now() "
            "WHERE id = $1 AND status = 'pending' RETURNING id;",
            suggestion_id, status, reviewed_by,
        )
        return updated is not None
