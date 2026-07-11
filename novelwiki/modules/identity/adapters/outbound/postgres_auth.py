from __future__ import annotations

import asyncpg

from novelwiki.modules.identity.adapters.outbound import rate_limit
from novelwiki.modules.identity.adapters.outbound.postgres_sessions import (
    create_session, revoke_session, revoke_user_sessions,
)
from novelwiki.modules.identity.adapters.outbound.postgres_users import unique_username
from novelwiki.modules.identity.adapters.outbound.tokens import hash_token
from novelwiki.modules.identity.application.ports import DuplicateRegistration


class PostgresAuthPersistence:
    """Identity-owned persistence used by the public authentication adapter."""

    def __init__(self, pool):
        self._pool = pool

    async def consume_rate(self, key: str, limit: object) -> None:
        async with self._pool.acquire() as connection:
            await rate_limit.consume(connection, key, limit)

    async def ensure_rate(self, key: str, limit: object) -> None:
        async with self._pool.acquire() as connection:
            await rate_limit.ensure_allowed(connection, key, limit)

    async def clear_rate(self, key: str) -> None:
        async with self._pool.acquire() as connection:
            await rate_limit.clear(connection, key)

    async def register_user(
        self, email: str, username: str, password_hash: str, token: str,
        expires_at, user_agent: str | None,
    ) -> tuple[dict, str]:
        async with self._pool.acquire() as connection:
            try:
                row = await connection.fetchrow(
                    """
                    INSERT INTO users (email, username, password_hash, display_name)
                    VALUES ($1, $2, $3, $4) RETURNING *;
                    """,
                    email, username, password_hash, username,
                )
            except asyncpg.UniqueViolationError as exc:
                field = "email" if "email" in str(exc).lower() else "username"
                raise DuplicateRegistration(field) from exc
            await connection.execute(
                "INSERT INTO email_tokens (user_id, kind, token_hash, expires_at) "
                "VALUES ($1, 'verify', $2, $3);",
                row["id"], hash_token(token), expires_at,
            )
            session = await create_session(connection, row["id"], user_agent)
        return dict(row), session

    async def find_login_user(self, identifier: str) -> dict | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                "SELECT * FROM users WHERE email = $1 OR username = $2;",
                identifier, identifier,
            )
        return dict(row) if row is not None else None

    async def create_user_session(self, user_id: int, user_agent: str | None) -> str:
        async with self._pool.acquire() as connection:
            return await create_session(connection, user_id, user_agent)

    async def revoke_session(self, token: str) -> None:
        async with self._pool.acquire() as connection:
            await revoke_session(connection, token)

    async def linked_providers(self, user_id: int) -> list[str]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT provider FROM oauth_accounts WHERE user_id = $1 ORDER BY provider;",
                user_id,
            )
        return [str(row["provider"]) for row in rows]

    async def change_password(
        self, user_id: int, password_hash: str, user_agent: str | None,
    ) -> str:
        async with self._pool.acquire() as connection:
            await connection.execute(
                "UPDATE users SET password_hash = $1, updated_at = now() WHERE id = $2;",
                password_hash, user_id,
            )
            await revoke_user_sessions(connection, user_id)
            return await create_session(connection, user_id, user_agent)

    async def verification_token_valid(self, token_hash: str) -> bool:
        async with self._pool.acquire() as connection:
            return bool(await connection.fetchval(
                """
                SELECT 1 FROM email_tokens
                WHERE token_hash = $1 AND kind = 'verify'
                  AND used_at IS NULL AND expires_at > now();
                """,
                token_hash,
            ))

    async def issue_reset_token(self, email: str, token: str, expires_at) -> bool:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow("SELECT id FROM users WHERE email = $1;", email)
            if row is None:
                return False
            await connection.execute(
                "INSERT INTO email_tokens (user_id, kind, token_hash, expires_at) "
                "VALUES ($1, 'reset', $2, $3);",
                row["id"], hash_token(token), expires_at,
            )
            return True

    async def reset_password(self, token_hash: str, password_hash: str) -> bool:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                UPDATE email_tokens SET used_at = now()
                WHERE token_hash = $1 AND kind = 'reset'
                  AND used_at IS NULL AND expires_at > now()
                RETURNING user_id;
                """,
                token_hash,
            )
            if row is None:
                return False
            await connection.execute(
                "UPDATE users SET password_hash = $1 WHERE id = $2;",
                password_hash, row["user_id"],
            )
            await revoke_user_sessions(connection, row["user_id"])
            return True

    async def confirm_verification(self, token_hash: str) -> bool:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                UPDATE email_tokens SET used_at = now()
                WHERE token_hash = $1 AND kind = 'verify'
                  AND used_at IS NULL AND expires_at > now()
                RETURNING user_id;
                """,
                token_hash,
            )
            if row is None:
                return False
            await connection.execute(
                "UPDATE users SET email_verified = TRUE WHERE id = $1;", row["user_id"],
            )
            return True

    async def oauth_login(
        self, provider: str, identity: dict, user_agent: str | None,
    ) -> tuple[dict, str]:
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                user = await self._find_or_create_oauth_user(connection, provider, identity)
                session = await create_session(connection, user["id"], user_agent)
        return user, session

    @staticmethod
    async def _find_or_create_oauth_user(connection, provider: str, identity: dict) -> dict:
        provider_id = identity["provider_account_id"]
        linked = await connection.fetchrow(
            """
            SELECT u.* FROM oauth_accounts oa JOIN users u ON u.id = oa.user_id
            WHERE oa.provider = $1 AND oa.provider_account_id = $2;
            """,
            provider, provider_id,
        )
        if linked is not None:
            return dict(linked)

        email = identity.get("email")
        email_verified = bool(identity.get("email_verified"))
        if email and email_verified:
            existing = await connection.fetchrow("SELECT * FROM users WHERE email = $1;", email)
            if existing is not None:
                await connection.execute(
                    "INSERT INTO oauth_accounts (user_id, provider, provider_account_id) "
                    "VALUES ($1, $2, $3) ON CONFLICT DO NOTHING;",
                    existing["id"], provider, provider_id,
                )
                return dict(existing)

        base = identity.get("name") or (email.split("@")[0] if email else provider + "_user")
        username = await unique_username(connection, base)
        placeholder_email = email if email_verified else f"{username}@{provider}.oauth.local"
        new = await connection.fetchrow(
            """
            INSERT INTO users (email, username, display_name, email_verified, password_hash)
            VALUES ($1, $2, $3, $4, NULL) RETURNING *;
            """,
            placeholder_email, username, identity.get("name") or username, email_verified,
        )
        await connection.execute(
            "INSERT INTO oauth_accounts (user_id, provider, provider_account_id) VALUES ($1, $2, $3);",
            new["id"], provider, provider_id,
        )
        return dict(new)
