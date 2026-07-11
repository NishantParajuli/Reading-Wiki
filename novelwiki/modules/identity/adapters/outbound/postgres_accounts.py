from __future__ import annotations

import json


class PostgresAccountRepository:
    def __init__(self, connection):
        self._connection = connection

    async def username_taken(self, username: str, excluding_user_id: int) -> bool:
        return bool(await self._connection.fetchval(
            "SELECT 1 FROM users WHERE username = $1 AND id <> $2;", username, excluding_user_id,
        ))

    async def update_profile(self, user_id: int, fields: dict) -> dict:
        sets, arguments = [], []
        for key, value in fields.items():
            arguments.append(json.dumps(value) if key == "prefs" else value)
            expression = f"COALESCE(prefs, '{{}}'::jsonb) || ${len(arguments)}::jsonb" if key == "prefs" else f"${len(arguments)}"
            sets.append(f"{key} = {expression}")
        arguments.append(user_id)
        row = await self._connection.fetchrow(
            f"UPDATE users SET {', '.join(sets)}, updated_at = now() "
            f"WHERE id = ${len(arguments)} RETURNING *;", *arguments,
        )
        return dict(row)

    async def set_avatar(self, user_id: int, relative_path: str) -> None:
        await self._connection.execute(
            "UPDATE users SET avatar_path = $1, updated_at = now() WHERE id = $2;",
            relative_path, user_id,
        )
