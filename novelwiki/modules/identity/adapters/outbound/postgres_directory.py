from __future__ import annotations

from novelwiki.modules.identity.public import UserLabel


class PostgresUserDirectory:
    def __init__(self, connection):
        self._connection = connection

    async def labels(self, user_ids: set[int]) -> dict[int, UserLabel]:
        if not user_ids:
            return {}
        rows = await self._connection.fetch(
            "SELECT id, username, display_name FROM users WHERE id = ANY($1::bigint[]);",
            sorted(user_ids),
        )
        return {
            int(row["id"]): UserLabel(
                user_id=int(row["id"]),
                username=row["username"],
                display_name=row["display_name"] or row["username"],
            )
            for row in rows
        }
