from __future__ import annotations


class PostgresIdentityAdminTransactionService:
    def __init__(self, connection):
        self._connection = connection

    async def user_role(self, user_id: int) -> str | None:
        return await self._connection.fetchval(
            "SELECT role FROM users WHERE id=$1;", user_id
        )

    async def other_admin_count(self, user_id: int) -> int:
        return int(await self._connection.fetchval(
            "SELECT COUNT(*) FROM users WHERE role='admin' AND id<>$1;", user_id
        ) or 0)

    async def update_user(self, user_id: int, fields) -> None:
        arguments: list[object] = []
        assignments: list[str] = []
        for key, value in fields.items():
            arguments.append(value)
            assignments.append(f"{key}=${len(arguments)}")
        arguments.append(user_id)
        await self._connection.execute(
            f"UPDATE users SET {', '.join(assignments)},updated_at=now() "
            f"WHERE id=${len(arguments)};", *arguments,
        )

    async def revoke_sessions(self, user_id: int) -> None:
        await self._connection.execute("DELETE FROM sessions WHERE user_id=$1;", user_id)

    async def delete_user(self, user_id: int) -> None:
        await self._connection.execute("DELETE FROM users WHERE id=$1;", user_id)
