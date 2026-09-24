import datetime as dt
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import novelwiki.auth.router as auth_router
import novelwiki.db.connection as db_connection
from novelwiki.auth.passwords import hash_password
from novelwiki.auth.tokens import hash_token
from novelwiki.config.settings import settings
from novelwiki.db.connection import close_db_pool, get_db_pool
from novelwiki.db.schema import init_database
from novelwiki.modules.identity.adapters.outbound.postgres_auth import PostgresAuthPersistence


REQUEST_HEADERS = {"X-Tideglass-Request": "1"}


async def _reset_pool():
    try:
        await close_db_pool()
    except RuntimeError:
        pass
    db_connection._pool = None


@pytest_asyncio.fixture()
async def auth_db(monkeypatch):
    async def fake_send(*args, **kwargs):
        return None

    monkeypatch.setattr(auth_router, "send_verification_email", fake_send)
    monkeypatch.setattr(auth_router, "send_reset_email", fake_send)
    await _reset_pool()
    await init_database()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM auth_rate_limits;")
            await conn.execute("DELETE FROM users CASCADE;")
    yield
    await _reset_pool()


async def _create_user(email: str, username: str, password: str, verified: bool = True) -> int:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        return await conn.fetchval(
            """
            INSERT INTO users (email, username, password_hash, display_name, email_verified)
            VALUES ($1, $2, $3, $2, $4)
            RETURNING id;
            """,
            email,
            username,
            hash_password(password),
            verified,
        )


class _FailAfterWritePool:
    """Inject a failure after a real SQL write, keeping real PostgreSQL transactions."""

    def __init__(self, pool, fragment):
        self.pool = pool
        self.fragment = fragment

    @asynccontextmanager
    async def acquire(self):
        async with self.pool.acquire() as connection:
            fragment = self.fragment

            class Connection:
                def __getattr__(self, name):
                    return getattr(connection, name)

                async def execute(self, query, *args):
                    result = await connection.execute(query, *args)
                    if fragment in query:
                        raise RuntimeError("injected identity write failure")
                    return result

            yield Connection()


@pytest.mark.parametrize(
    "operation,failing_write",
    [
        ("register", "INSERT INTO sessions"),
        ("change", "INSERT INTO sessions"),
        ("reset", "DELETE FROM sessions"),
        ("verify", "UPDATE users SET email_verified"),
    ],
)
@pytest.mark.asyncio
async def test_identity_mutations_roll_back_all_writes_and_remain_retryable(
    auth_db, operation, failing_write,
):
    pool = await get_db_pool()
    persistence = PostgresAuthPersistence(pool)
    token = "atomic-identity-token"
    token_hash = hash_token(token)
    expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1)
    user_id = None
    if operation != "register":
        user_id = await _create_user(
            "atomic@example.test", "atomicuser", "OriginalPassword123", verified=False,
        )
        await persistence.create_user_session(user_id, "original device")
        async with pool.acquire() as connection:
            await connection.execute(
                "INSERT INTO email_tokens (user_id,kind,token_hash,expires_at) "
                "VALUES ($1,$2,$3,$4);",
                user_id, "verify" if operation == "verify" else "reset", token_hash, expires,
            )

    async def snapshot():
        async with pool.acquire() as connection:
            return {
                "users": [dict(row) for row in await connection.fetch("SELECT * FROM users ORDER BY id")],
                "tokens": [dict(row) for row in await connection.fetch("SELECT * FROM email_tokens ORDER BY id")],
                "sessions": [dict(row) for row in await connection.fetch("SELECT * FROM sessions ORDER BY token_hash")],
            }

    async def mutate(adapter):
        if operation == "register":
            return await adapter.register_user(
                "atomic@example.test", "atomicuser", "new-password-hash", token,
                expires, "new device",
            )
        if operation == "change":
            return await adapter.change_password(user_id, "new-password-hash", "new device")
        if operation == "reset":
            return await adapter.reset_password(token_hash, "new-password-hash")
        return await adapter.confirm_verification(token_hash)

    before = await snapshot()
    with pytest.raises(RuntimeError, match="injected identity write failure"):
        await mutate(PostgresAuthPersistence(_FailAfterWritePool(pool, failing_write)))
    assert await snapshot() == before

    # A failed request leaves its account/token/session state usable for a retry.
    assert await mutate(persistence)
    after = await snapshot()
    if operation == "verify":
        assert after["users"][0]["email_verified"] is True
        assert after["tokens"][0]["used_at"] is not None
        assert after["sessions"] == before["sessions"]
    else:
        assert after["users"][0]["password_hash"] == "new-password-hash"
        assert len(after["sessions"]) == (0 if operation == "reset" else 1)
        if operation == "change":
            assert after["sessions"][0]["token_hash"] != before["sessions"][0]["token_hash"]
        if operation == "reset":
            assert after["tokens"][0]["used_at"] is not None


@pytest.mark.asyncio
async def test_failed_login_attempts_are_rate_limited_by_account(auth_db, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_LOGIN_ACCOUNT_LIMIT", 2)
    monkeypatch.setattr(settings, "AUTH_LOGIN_IP_LIMIT", 100)
    await _create_user("login-account@example.test", "loginacct", "CorrectPass123")

    from novelwiki.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        statuses = []
        for _ in range(3):
            res = await client.post(
                "/api/auth/login",
                headers=REQUEST_HEADERS,
                json={"identifier": "login-account@example.test", "password": "wrong-password"},
            )
            statuses.append(res.status_code)

    assert statuses == [401, 401, 429]


@pytest.mark.asyncio
async def test_failed_login_attempts_are_rate_limited_by_ip(auth_db, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_LOGIN_ACCOUNT_LIMIT", 100)
    monkeypatch.setattr(settings, "AUTH_LOGIN_IP_LIMIT", 2)

    from novelwiki.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        statuses = []
        for i in range(3):
            res = await client.post(
                "/api/auth/login",
                headers=REQUEST_HEADERS,
                json={"identifier": f"missing-{i}@example.test", "password": "wrong-password"},
            )
            statuses.append(res.status_code)

    assert statuses == [401, 401, 429]


@pytest.mark.asyncio
async def test_successful_login_still_works_below_threshold(auth_db, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_LOGIN_ACCOUNT_LIMIT", 3)
    monkeypatch.setattr(settings, "AUTH_LOGIN_IP_LIMIT", 3)
    await _create_user("login-ok@example.test", "loginok", "CorrectPass123")

    from novelwiki.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        bad = await client.post(
            "/api/auth/login",
            headers=REQUEST_HEADERS,
            json={"identifier": "login-ok@example.test", "password": "wrong-password"},
        )
        good = await client.post(
            "/api/auth/login",
            headers=REQUEST_HEADERS,
            json={"identifier": "login-ok@example.test", "password": "CorrectPass123"},
        )

    assert bad.status_code == 401
    assert good.status_code == 200
    assert settings.SESSION_COOKIE in good.cookies
    assert settings.CSRF_COOKIE in good.cookies


@pytest.mark.asyncio
async def test_reset_requests_remain_generic_but_stop_issuing_tokens(auth_db, monkeypatch):
    sent = []

    async def fake_reset(email, link):
        sent.append((email, link))

    monkeypatch.setattr(auth_router, "send_reset_email", fake_reset)
    monkeypatch.setattr(settings, "AUTH_RESET_REQUEST_EMAIL_LIMIT", 1)
    monkeypatch.setattr(settings, "AUTH_RESET_REQUEST_IP_LIMIT", 100)
    user_id = await _create_user("reset@example.test", "resetuser", "CorrectPass123")

    from novelwiki.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        first = await client.post(
            "/api/auth/request-reset",
            headers=REQUEST_HEADERS,
            json={"email": "reset@example.test"},
        )
        second = await client.post(
            "/api/auth/request-reset",
            headers=REQUEST_HEADERS,
            json={"email": "reset@example.test"},
        )

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        token_count = await conn.fetchval(
            "SELECT count(*) FROM email_tokens WHERE user_id = $1 AND kind = 'reset';",
            user_id,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == {"status": "ok"}
    assert second.json() == {"status": "ok"}
    assert len(sent) == 1
    assert token_count == 1


@pytest.mark.asyncio
async def test_invalid_reset_token_submissions_are_rate_limited(auth_db, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_RESET_SUBMIT_TOKEN_LIMIT", 2)
    monkeypatch.setattr(settings, "AUTH_RESET_SUBMIT_IP_LIMIT", 100)

    from novelwiki.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        statuses = []
        for _ in range(3):
            res = await client.post(
                "/api/auth/reset",
                headers=REQUEST_HEADERS,
                json={"token": "not-a-real-reset-token", "password": "NewPassword123"},
            )
            statuses.append(res.status_code)

    assert statuses == [400, 400, 429]


@pytest.mark.asyncio
async def test_verify_get_does_not_consume_token_and_post_consumes_once(auth_db):
    raw_token = "scanner-safe-token"
    user_id = await _create_user("verify@example.test", "verifyuser", "CorrectPass123", verified=False)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO email_tokens (user_id, kind, token_hash, expires_at)
            VALUES ($1, 'verify', $2, $3);
            """,
            user_id,
            hash_token(raw_token),
            dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=1),
        )

    from novelwiki.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver", follow_redirects=False) as client:
        preview = await client.get(f"/api/auth/verify?token={raw_token}")

    async with pool.acquire() as conn:
        after_get = await conn.fetchrow(
            """
            SELECT u.email_verified, t.used_at
            FROM users u
            JOIN email_tokens t ON t.user_id = u.id
            WHERE u.id = $1 AND t.kind = 'verify';
            """,
            user_id,
        )

    assert preview.status_code == 303
    assert preview.headers["location"] == f"/verify?token={raw_token}"
    assert after_get["email_verified"] is False
    assert after_get["used_at"] is None

    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        confirm = await client.post(
            "/api/auth/verify",
            headers=REQUEST_HEADERS,
            json={"token": raw_token},
        )
        replay = await client.post(
            "/api/auth/verify",
            headers=REQUEST_HEADERS,
            json={"token": raw_token},
        )

    async with pool.acquire() as conn:
        after_post = await conn.fetchrow(
            """
            SELECT u.email_verified, t.used_at
            FROM users u
            JOIN email_tokens t ON t.user_id = u.id
            WHERE u.id = $1 AND t.kind = 'verify';
            """,
            user_id,
        )

    assert confirm.status_code == 200
    assert replay.status_code == 400
    assert after_post["email_verified"] is True
    assert after_post["used_at"] is not None
