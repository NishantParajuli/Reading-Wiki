from __future__ import annotations

from typing import Any

from ...public import NovelAccess


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
