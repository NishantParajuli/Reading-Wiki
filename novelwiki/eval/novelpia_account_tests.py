"""Real PostgreSQL/session regression tests; conftest creates a disposable database."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import novelwiki.db.connection as db_connection
from novelwiki.bootstrap.account_cookies import build_account_cookie_repository, build_account_cookie_service
from novelwiki.db.connection import close_db_pool, get_db_pool
from novelwiki.db.schema import init_database
from novelwiki.modules.identity.adapters.outbound.postgres_auth import PostgresAuthPersistence
from novelwiki.platform.config import settings


SYNTHETIC_COOKIE = "novelpia-integration-test-token-not-a-real-account"


def export(value=SYNTHETIC_COOKIE):
    return [{"name": "TKEY", "value": value, "domain": ".novelpia.com",
             "path": "/", "session": True, "httpOnly": True},
            {"name": "analytics", "value": "discard-me", "domain": ".novelpia.com"}]


async def reset_pool():
    try:
        await close_db_pool()
    except RuntimeError:
        pass
    db_connection._pool = None


@pytest_asyncio.fixture()
async def cookie_db(monkeypatch):
    await reset_pool()
    monkeypatch.setattr(settings, "SESSION_SECRET", "synthetic-novelpia-integration-encryption-key")
    await init_database()
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        await connection.execute("DELETE FROM users CASCADE")
        users = []
        for name in ("cookie_owner", "cookie_other"):
            users.append(await connection.fetchval(
                "INSERT INTO users(email,username,email_verified) VALUES($1,$2,TRUE) RETURNING id",
                name + "@example.test", name,
            ))
    sessions = PostgresAuthPersistence(pool)
    tokens = [await sessions.create_user_session(user, "cookie integration") for user in users]
    yield SimpleNamespace(owner=users[0], other=users[1], owner_token=tokens[0], other_token=tokens[1])
    await reset_pool()


@pytest.mark.asyncio
async def test_encrypted_cookies_survive_pool_reload_and_are_deleted_with_owner(cookie_db):
    service = await build_account_cookie_service()
    result = await service.replace(cookie_db.owner, export())
    assert result["configured"] and result["usable"]
    assert SYNTHETIC_COOKIE not in str(result)
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch("SELECT * FROM acquisition_account_cookies")
    assert len(rows) == 1
    row = rows[0]
    assert row["user_id"] == cookie_db.owner and row["provider"] == "novelpia-global"
    assert SYNTHETIC_COOKIE not in row["ciphertext"] and "discard-me" not in row["ciphertext"]
    first_ciphertext = row["ciphertext"]

    # A new pool and newly composed repository must read the persisted connection.
    await reset_pool()
    repository = await build_account_cookie_repository()
    cookies, updated_at = await repository.read(cookie_db.owner)
    assert [cookie["name"] for cookie in cookies] == ["TKEY"]
    assert cookies[0]["value"] == SYNTHETIC_COOKIE and updated_at is not None
    assert await repository.read(cookie_db.other) == ([], None)
    service = await build_account_cookie_service()
    await service.replace(cookie_db.owner, export("replacement-synthetic-token"))
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        rows = await connection.fetch("SELECT * FROM acquisition_account_cookies")
        assert len(rows) == 1 and rows[0]["ciphertext"] != first_ciphertext
        await connection.execute("DELETE FROM users WHERE id=$1", cookie_db.owner)
        assert await connection.fetchval("SELECT count(*) FROM acquisition_account_cookies") == 0


@pytest.mark.asyncio
async def test_settings_routes_use_real_session_isolation_and_recover_after_key_rotation(cookie_db, monkeypatch, caplog):
    from novelwiki.api.app import app

    url = "/api/settings/novelpia-cookies"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as owner, \
               AsyncClient(transport=transport, base_url="https://testserver") as other:
        assert (await owner.get(url)).status_code == 401
        owner.cookies.set(settings.SESSION_COOKIE, cookie_db.owner_token)
        owner.cookies.set(settings.CSRF_COOKIE, "owner-csrf")
        other.cookies.set(settings.SESSION_COOKIE, cookie_db.other_token)
        other.cookies.set(settings.CSRF_COOKIE, "other-csrf")
        owner_headers = {"X-Tideglass-CSRF": "owner-csrf"}
        other_headers = {"X-Tideglass-CSRF": "other-csrf"}

        assert (await owner.put(url, json={"cookies": export()})).status_code == 403
        response = await owner.put(url, json={"cookies": export()}, headers=owner_headers)
        assert response.status_code == 200 and response.json()["usable"]
        assert response.headers["cache-control"] == "no-store"
        assert SYNTHETIC_COOKIE not in response.text
        assert not (await other.get(url)).json()["configured"]
        await other.delete(url, headers=other_headers)
        assert (await owner.get(url)).json()["configured"]
        response = await other.put(url, json={"cookies": export(), "user_id": cookie_db.owner}, headers=other_headers)
        assert response.status_code == 422 and SYNTHETIC_COOKIE not in response.text

        # Existing Tideglass sessions survive secret rotation. Replacement works
        # even when the previous encrypted account connection cannot be opened.
        monkeypatch.setattr(settings, "SESSION_SECRET", "rotated-synthetic-encryption-key")
        response = await owner.get(url)
        assert response.status_code == 422 and "Replace them" in response.json()["detail"]
        response = await owner.put(url, json={"cookies": export("fresh-synthetic-token")}, headers=owner_headers)
        assert response.status_code == 200 and response.json()["usable"]
        assert (await owner.get(url)).json()["configured"]
        response = await owner.delete(url, headers=owner_headers)
        assert response.status_code == 200 and not response.json()["configured"]
        assert not (await owner.get(url)).json()["configured"]
        pool = await get_db_pool()
        async with pool.acquire() as connection:
            assert await connection.fetchval("SELECT count(*) FROM acquisition_account_cookies") == 0
    assert SYNTHETIC_COOKIE not in caplog.text and "fresh-synthetic-token" not in caplog.text
