from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from novelwiki.kernel.errors import ValidationFailed
from novelwiki.modules.acquisition.adapters.inbound import account_cookies_http as http
from novelwiki.modules.acquisition.adapters.inbound.jobs import execute_scrape_job
from novelwiki.modules.acquisition.adapters.outbound.account_cookies import CookieCipher, PostgresAccountCookieRepository
from novelwiki.modules.acquisition.application.account_cookies import AccountCookieService
from novelwiki.modules.acquisition.domain.account_cookies import cookie_metadata, normalize_novelpia_cookies
from novelwiki.platform.auth import current_user

SECRET = "synthetic-private-cookie-value"


def export(**changes):
    return [{"name": "TKEY", "value": SECRET, "domain": ".novelpia.com", "path": "/",
             "expirationDate": 2000000000, **changes}]


def test_export_keeps_only_authentication_and_metadata_has_no_values():
    cookies = normalize_novelpia_cookies(export() + [
        {"name": "analytics", "value": "tracking", "domain": ".novelpia.com"},
        {"name": "CloudFront-Signature", "value": "temporary", "domain": ".novelpia.com"},
        {"name": "unrelated", "value": "another-site", "domain": ".google.com"},
    ])
    assert [item["name"] for item in cookies] == ["TKEY"]
    metadata = cookie_metadata(cookies, datetime(2026, 1, 1, tzinfo=UTC))
    assert metadata["configured"] and metadata["usable"]
    assert SECRET not in str(metadata) and "value" not in metadata["cookies"][0]
    assert metadata["updated_at"] == "2026-01-01T00:00:00+00:00"


@pytest.mark.parametrize("changes", [
    {"value": "bad\r\nCookie: secret"}, {"value": "bad;other=1"}, {"value": 'bad"quote'},
    {"value": "bad\\slash"}, {"value": "bad,comma"}, {"value": "雪"}, {"value": ""},
    {"value": "x" * 8193}, {"value": []}, {"name": []}, {"domain": []},
    {"domain": "evilnovelpia.com"}, {"domain": "novelpia.com.evil.test"},
    {"domain": "api-g.novelpia.com"}, {"path": "/login"},
    {"session": "false"}, {"expirationDate": float("nan")},
    {"expirationDate": float("inf")}, {"expirationDate": True},
    {"expirationDate": "2000000000"}, {"expirationDate": 1e200},
])
def test_bad_cookie_rejected_without_echoing_input(changes):
    with pytest.raises(ValidationFailed) as error:
        normalize_novelpia_cookies(export(**changes))
    assert SECRET not in str(error.value)


@pytest.mark.parametrize("bad", [None, {}, [], ["cookie"], export() * 2, export() * 101,
                                      [{"name": "LOGINKEY", "value": "abc", "domain": ".novelpia.com"}]])
def test_invalid_export_or_missing_refresh_token_rejected(bad):
    with pytest.raises(ValidationFailed):
        normalize_novelpia_cookies(bad)


def test_local_expiry_status_and_session_cookies():
    assert not cookie_metadata(normalize_novelpia_cookies(export(expirationDate=1)))["usable"]
    assert cookie_metadata(normalize_novelpia_cookies(export(session=True, expirationDate=1)))["usable"]
    assert cookie_metadata([]) == {"configured": False, "usable": False, "updated_at": None, "cookies": []}


def test_encryption_binds_credentials_to_user_and_installation():
    cipher = CookieCipher("a-private-installation-secret")
    cookies = normalize_novelpia_cookies(export())
    encrypted = cipher.encrypt(10, cookies)
    assert SECRET not in encrypted
    assert cipher.decrypt(10, encrypted) == cookies
    for other, owner, token in [(cipher, 20, encrypted), (CookieCipher("another-secret"), 10, encrypted),
                                (cipher, 10, encrypted[:-3] + "bad")]:
        with pytest.raises(ValidationFailed, match="Replace them in Settings"):
            other.decrypt(owner, token)
    with pytest.raises(ValidationFailed, match="SESSION_SECRET"):
        CookieCipher("dev-insecure-change-me").encrypt(10, cookies)


@pytest.mark.asyncio
async def test_repository_encryption_and_queries_are_scoped():
    connection = SimpleNamespace(fetchrow=AsyncMock(), fetchval=AsyncMock(return_value=datetime.now(UTC)),
                                 execute=AsyncMock())
    @asynccontextmanager
    async def acquire():
        yield connection
    repository = PostgresAccountCookieRepository(SimpleNamespace(acquire=acquire), CookieCipher("private-secret"))
    cookies = normalize_novelpia_cookies(export())
    await repository.replace(7, cookies)
    arguments = connection.fetchval.await_args.args
    assert arguments[1] == 7 and SECRET not in arguments[2]
    connection.fetchrow.return_value = {"ciphertext": arguments[2], "updated_at": datetime.now(UTC)}
    assert (await repository.read(7))[0] == cookies
    assert connection.fetchrow.await_args.args[1] == 7
    with pytest.raises(ValidationFailed):
        await repository.read(8)
    await repository.delete(8)
    assert connection.execute.await_args.args[1] == 8


class MemoryRepository:
    def __init__(self):
        self.rows = {}
    async def read(self, user_id):
        return self.rows.get(user_id, ([], None))
    async def replace(self, user_id, cookies):
        now = datetime.now(UTC)
        self.rows[user_id] = (cookies, now)
        return now
    async def delete(self, user_id):
        self.rows.pop(user_id, None)


@pytest.mark.asyncio
async def test_http_write_only_isolation_replacement_delete_and_no_echo():
    app = FastAPI()
    app.include_router(http.router, prefix="/api")
    repository = MemoryRepository()
    service = AccountCookieService(repository)
    actor = {"id": 1}
    app.dependency_overrides[current_user] = lambda: actor
    app.dependency_overrides[http.account_cookie_service_dependency] = lambda: service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        url = "/api/settings/novelpia-cookies"
        response = await client.put(url, json={"cookies": export()})
        assert response.status_code == 200 and response.json()["usable"]
        assert SECRET not in response.text and response.headers["cache-control"] == "no-store"
        assert SECRET not in (await client.get(url)).text
        actor["id"] = 2
        assert not (await client.get(url)).json()["configured"]
        await client.delete(url)
        assert 1 in repository.rows
        actor["id"] = 1
        response = await client.put(url, json={"cookies": export(value="replacement")})
        assert response.status_code == 200 and repository.rows[1][0][0]["value"] == "replacement"
        for payload in [{"cookies": SECRET}, {"cookies": [{"value": SECRET}]},
                        {"cookies": export(), "user_id": 2}, [SECRET]]:
            response = await client.put(url, json=payload)
            assert response.status_code == 422 and SECRET not in response.text
        response = await client.put(url, content='{"cookies": "' + SECRET)
        assert response.status_code == 422 and SECRET not in response.text
        response = await client.put(url, content="x" * 65537)
        assert response.status_code == 413
        assert (await client.delete(url)).json()["configured"] is False
        assert not (await client.get(url)).json()["configured"]


@pytest.mark.asyncio
async def test_http_requires_authentication_before_processing_export():
    app = FastAPI()
    app.include_router(http.router)
    async def anonymous():
        raise HTTPException(401, "Sign in")
    app.dependency_overrides[current_user] = anonymous
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        for method in ("GET", "PUT", "DELETE"):
            response = await client.request(method, "/settings/novelpia-cookies", json={"cookies": export()})
            assert response.status_code == 401 and SECRET not in response.text


@pytest.mark.asyncio
@pytest.mark.parametrize("source_id", [None, 99])
async def test_job_uses_actor_identity_not_options_override(source_id):
    context = SimpleNamespace(bail_if_canceled=AsyncMock(), update_job=AsyncMock(),
                              scrape_source=AsyncMock(return_value=1), scrape_novel=AsyncMock(return_value=1))
    await execute_scrape_job({"id": 1, "novel_id": 2, "user_id": 3,
                             "options": {"source_id": source_id, "credential_user_id": 999}}, context)
    operation = context.scrape_source if source_id else context.scrape_novel
    assert operation.await_args.kwargs["credential_user_id"] == 3


@pytest.mark.asyncio
async def test_real_web_middleware_never_reflects_secret_inputs_and_keeps_csrf(caplog):
    from novelwiki.platform.config import settings
    from novelwiki.platform.web.factory import create_web_app
    app = create_web_app(lifespan=None, seed_csrf_cookie=lambda response: None)
    app.include_router(http.router, prefix="/api")
    service = AccountCookieService(MemoryRepository())
    app.dependency_overrides[current_user] = lambda: {"id": 1}
    app.dependency_overrides[http.account_cookie_service_dependency] = lambda: service
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        url = "/api/settings/novelpia-cookies"
        response = await client.put(url, json={"cookies": export()})
        assert response.status_code == 403
        client.cookies.set(settings.CSRF_COOKIE, "synthetic-csrf")
        headers = {"x-tideglass-csrf": "synthetic-csrf"}
        for payload in [SECRET, {"cookies": SECRET}, {"cookies": export(expirationDate=SECRET)},
                        {"cookies": export(domain=SECRET)}, {"cookies": export(value=SECRET + ";")},
                        {"cookies": export(), "unexpected": SECRET}]:
            response = await client.put(url, json=payload, headers=headers)
            assert response.status_code == 422 and SECRET not in response.text
            assert response.headers["cache-control"] == "no-store"
        response = await client.put(url, content='{"cookies": "' + SECRET, headers=headers)
        assert response.status_code == 422 and SECRET not in response.text
        assert SECRET not in caplog.text
