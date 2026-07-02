import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import novelwiki.auth.router as auth_router
import novelwiki.db.connection as db_connection
from novelwiki.config.settings import settings
from novelwiki.db.connection import close_db_pool, get_db_pool
from novelwiki.db.schema import init_database
from novelwiki.importer import storage


REQUEST_HEADERS = {"X-Tideglass-Request": "1"}


async def _reset_pool():
    try:
        await close_db_pool()
    except RuntimeError:
        pass
    db_connection._pool = None


@pytest_asyncio.fixture()
async def csrf_db(tmp_path, monkeypatch):
    async def fake_send(*args, **kwargs):
        return None

    monkeypatch.setattr(auth_router, "send_verification_email", fake_send)
    monkeypatch.setattr(settings, "ASSET_DIR", str(tmp_path / "assets"))
    storage.ensure_dirs()
    await _reset_pool()
    await init_database()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM auth_rate_limits;")
            await conn.execute("DELETE FROM users CASCADE;")
    yield
    await _reset_pool()


async def _register(client: AsyncClient, email: str = "csrf@example.test") -> str:
    res = await client.post(
        "/api/auth/register",
        headers=REQUEST_HEADERS,
        json={"email": email, "username": email.split("@")[0].replace("-", "_"), "password": "CorrectPass123"},
    )
    assert res.status_code == 200
    csrf = client.cookies.get(settings.CSRF_COOKIE)
    assert csrf
    return csrf


@pytest.mark.asyncio
async def test_public_auth_mutations_require_custom_header(csrf_db):
    from novelwiki.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        res = await client.post(
            "/api/auth/login",
            json={"identifier": "missing@example.test", "password": "wrong-password"},
        )

    assert res.status_code == 403
    assert res.json()["detail"] == "Missing required request header."


@pytest.mark.asyncio
async def test_state_changing_json_route_requires_csrf_header(csrf_db):
    from novelwiki.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        csrf = await _register(client)
        blocked = await client.patch("/api/me", json={"display_name": "Blocked"})
        allowed = await client.patch(
            "/api/me",
            headers={"X-Tideglass-Request": "1", "X-Tideglass-CSRF": csrf},
            json={"display_name": "Allowed"},
        )

    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "CSRF token missing or invalid."
    assert allowed.status_code == 200
    assert allowed.json()["display_name"] == "Allowed"


@pytest.mark.asyncio
async def test_state_changing_multipart_route_requires_csrf_header(csrf_db):
    from novelwiki.api.app import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://testserver") as client:
        csrf = await _register(client, "csrf-avatar@example.test")
        blocked = await client.post(
            "/api/me/avatar",
            files={"file": ("avatar.png", b"not really a png", "image/png")},
        )
        allowed = await client.post(
            "/api/me/avatar",
            headers={"X-Tideglass-Request": "1", "X-Tideglass-CSRF": csrf},
            files={"file": ("avatar.png", b"not really a png", "image/png")},
        )

    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "CSRF token missing or invalid."
    assert allowed.status_code == 200
    assert allowed.json()["avatar_url"].startswith("/assets/_users/")
