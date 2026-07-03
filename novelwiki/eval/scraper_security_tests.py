from contextlib import asynccontextmanager
import asyncio
import ipaddress
from types import SimpleNamespace

import pytest
import pytest_asyncio
from curl_cffi.requests import AsyncSession
from fastapi import HTTPException

import novelwiki.db.connection as db_connection
from novelwiki.api import routes
from novelwiki.db.connection import close_db_pool, get_db_pool
from novelwiki.db.schema import init_database
from novelwiki.scraper import safe_fetch
from novelwiki.scraper.runner import scrape_source


async def _reset_pool():
    try:
        await close_db_pool()
    except RuntimeError:
        pass
    db_connection._pool = None


class FakeResponse:
    def __init__(self, status_code=200, headers=None, chunks=None, url="http://public.example/", primary_ip="8.8.8.8"):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks or []
        self.url = url
        self.primary_ip = primary_ip

    async def aiter_content(self):
        for chunk in self._chunks:
            yield chunk


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    @asynccontextmanager
    async def stream(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        if not self.responses:
            raise AssertionError(f"Unexpected fetch: {url}")
        yield self.responses.pop(0)


@pytest_asyncio.fixture()
async def scraper_db():
    await _reset_pool()
    await init_database()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM chapters CASCADE;")
            await conn.execute("DELETE FROM novels CASCADE;")
            await conn.execute("DELETE FROM users CASCADE;")

            owner_a = await conn.fetchrow(
                """
                INSERT INTO users (email, username, display_name, role, email_verified)
                VALUES ('owner-a@example.test', 'ownera', 'Owner A', 'user', TRUE)
                RETURNING *;
                """
            )
            owner_b = await conn.fetchrow(
                """
                INSERT INTO users (email, username, display_name, role, email_verified)
                VALUES ('owner-b@example.test', 'ownerb', 'Owner B', 'user', TRUE)
                RETURNING *;
                """
            )
            novel_a = await conn.fetchval(
                "INSERT INTO novels (title, owner_id, visibility) VALUES ('Novel A', $1, 'private') RETURNING id;",
                owner_a["id"],
            )
            novel_b = await conn.fetchval(
                "INSERT INTO novels (title, owner_id, visibility) VALUES ('Novel B', $1, 'private') RETURNING id;",
                owner_b["id"],
            )
            source_a = await conn.fetchval(
                """
                INSERT INTO sources (novel_id, adapter, start_url, config, language, is_raw)
                VALUES ($1, 'fenrirealm', 'https://public.example/chapter-1', '{}'::jsonb, 'en', FALSE)
                RETURNING id;
                """,
                novel_a,
            )
            source_b = await conn.fetchval(
                """
                INSERT INTO sources (novel_id, adapter, start_url, config, language, is_raw)
                VALUES ($1, 'fenrirealm', 'https://public.example/chapter-1', '{}'::jsonb, 'en', FALSE)
                RETURNING id;
                """,
                novel_b,
            )
    yield {
        "owner_a": dict(owner_a),
        "owner_b": dict(owner_b),
        "novel_a": int(novel_a),
        "novel_b": int(novel_b),
        "source_a": int(source_a),
        "source_b": int(source_b),
    }
    await _reset_pool()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/chapter",
        "http://127.0.0.1/chapter",
        "http://[::1]/chapter",
        "http://10.0.0.1/chapter",
        "http://172.16.0.1/chapter",
        "http://192.168.1.1/chapter",
        "http://169.254.169.254/latest/meta-data/",
        "http://[fc00::1]/chapter",
        "http://[fe80::1]/chapter",
        "file:///etc/passwd",
        "gopher://example.com/",
        "https://user:pass@example.com/chapter",
        "https://example.com:99999/chapter",
    ],
)
async def test_private_and_unsupported_start_urls_are_rejected(url):
    with pytest.raises(safe_fetch.UnsafeUrlError):
        await safe_fetch.validate_source_start_url(url)


@pytest.mark.asyncio
async def test_dns_resolution_to_private_address_is_rejected(monkeypatch):
    async def fake_resolve(host, port):
        return [ipaddress.ip_address("10.0.0.5")]

    monkeypatch.setattr(safe_fetch, "_resolve_host", fake_resolve)

    with pytest.raises(safe_fetch.UnsafeUrlError, match="non-public"):
        await safe_fetch.validate_source_start_url("https://public.example/chapter-1")


@pytest.mark.asyncio
async def test_redirect_to_private_address_is_rejected_before_second_fetch(monkeypatch):
    async def fake_resolve(host, port):
        return [ipaddress.ip_address("8.8.8.8")]

    monkeypatch.setattr(safe_fetch, "_resolve_host", fake_resolve)
    session = FakeSession([
        FakeResponse(status_code=302, headers={"location": "http://127.0.0.1/admin"}),
    ])

    with pytest.raises(safe_fetch.UnsafeUrlError):
        await safe_fetch.safe_fetch(
            session,
            "https://public.example/chapter-1",
            source_host="public.example",
        )

    assert [req[1] for req in session.requests] == ["https://public.example/chapter-1"]


@pytest.mark.asyncio
async def test_discovered_private_next_link_stops_without_network_fetch(monkeypatch):
    async def fake_resolve(host, port):
        return [ipaddress.ip_address("8.8.8.8")]

    monkeypatch.setattr(safe_fetch, "_resolve_host", fake_resolve)
    session = FakeSession([])

    with pytest.raises(safe_fetch.UnsafeUrlError):
        await safe_fetch.safe_fetch(
            session,
            "http://10.0.0.1/chapter-2",
            source_host="public.example",
        )

    assert session.requests == []


@pytest.mark.asyncio
async def test_response_size_cap_aborts_stream(monkeypatch):
    async def fake_resolve(host, port):
        return [ipaddress.ip_address("8.8.8.8")]

    monkeypatch.setattr(safe_fetch, "_resolve_host", fake_resolve)
    session = FakeSession([
        FakeResponse(chunks=[b"abc", b"def"], url="https://public.example/chapter-1"),
    ])

    with pytest.raises(safe_fetch.ResponseTooLargeError):
        await safe_fetch.safe_fetch(
            session,
            "https://public.example/chapter-1",
            source_host="public.example",
            max_bytes=4,
        )


@pytest.mark.asyncio
async def test_real_curl_session_does_not_pass_unsupported_curl_options(monkeypatch):
    async def handle(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async def fake_validate_url(*_args, **_kwargs):
        return SimpleNamespace(
            url=f"http://127.0.0.1:{port}/ok",
            host="public.example",
            port=port,
            ips=(ipaddress.ip_address("8.8.8.8"),),
            curl_resolve=(f"public.example:{port}:8.8.8.8",),
        )

    monkeypatch.setattr(safe_fetch, "validate_url", fake_validate_url)
    try:
        async with AsyncSession() as session:
            with pytest.raises(safe_fetch.UnsafeUrlError):
                await safe_fetch.safe_fetch(session, "https://public.example/ok")
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_real_curl_session_reads_body_and_headers(monkeypatch):
    """Drive the *real* curl_cffi request+streaming path end-to-end against a local
    stub: this exercises stream() kwargs, aiter_content(), header parsing and text
    decode for real, so a future incompatibility on the read path can't hide behind
    a mocked session. Loopback isn't public, so relax only the address guard."""
    async def handle(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        body = b"hello world"
        writer.write(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/plain; charset=utf-8\r\n"
            b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(safe_fetch, "_ensure_public_ip", lambda ip: None)
    try:
        async with AsyncSession() as session:
            resp = await safe_fetch.safe_fetch(session, f"http://127.0.0.1:{port}/ok")
            text = await safe_fetch.safe_fetch_text(session, f"http://127.0.0.1:{port}/ok")
    finally:
        server.close()
        await server.wait_closed()

    assert resp.status_code == 200
    assert resp.body == b"hello world"
    assert resp.headers["content-type"].startswith("text/plain")
    assert text == "hello world"


@pytest.mark.asyncio
async def test_real_curl_session_follows_validated_redirect(monkeypatch):
    """safe_fetch handles redirects itself (allow_redirects=False) and re-validates
    each hop. Prove the manual redirect loop works against a real curl session, not
    just the FakeSession."""
    async def handle(reader, writer):
        req = await reader.readuntil(b"\r\n\r\n")
        if b"GET /start " in req:
            writer.write(b"HTTP/1.1 302 Found\r\nLocation: /final\r\nContent-Length: 0\r\n\r\n")
        else:
            body = b"final page"
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
            )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    monkeypatch.setattr(safe_fetch, "_ensure_public_ip", lambda ip: None)
    try:
        async with AsyncSession() as session:
            resp = await safe_fetch.safe_fetch(session, f"http://127.0.0.1:{port}/start")
    finally:
        server.close()
        await server.wait_closed()

    assert resp.status_code == 200
    assert resp.body == b"final page"


@pytest.mark.asyncio
async def test_scrape_route_rejects_source_from_another_novel(scraper_db):
    with pytest.raises(HTTPException) as exc:
        await routes.api_scrape(
            scraper_db["novel_a"],
            routes.ScrapeTrigger(source_id=scraper_db["source_b"]),
            user=scraper_db["owner_a"],
        )

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_scrape_route_schedules_owned_source_durable_job(scraper_db):
    # Scraping is now a durable job; the worker passes the job's novel_id as expected_novel_id
    # into scrape_source (the ownership guard verified by the worker test below).
    from novelwiki.jobs import service as jobs_service

    result = await routes.api_scrape(
        scraper_db["novel_a"],
        routes.ScrapeTrigger(source_id=scraper_db["source_a"]),
        user=scraper_db["owner_a"],
    )

    assert result["status"] == "success" and result["deduped"] is False
    job = await jobs_service.get_job(result["job_id"])
    assert job["kind"] == "scrape" and job["status"] == "queued"
    assert job["novel_id"] == scraper_db["novel_a"]
    assert job["options"]["source_id"] == scraper_db["source_a"]


@pytest.mark.asyncio
async def test_worker_expected_novel_mismatch_aborts_without_writing(scraper_db):
    count = await scrape_source(scraper_db["source_b"], expected_novel_id=scraper_db["novel_a"])

    assert count == 0
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        assert await conn.fetchval("SELECT COUNT(*) FROM chapters WHERE source_id = $1;", scraper_db["source_b"]) == 0
