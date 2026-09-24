from contextlib import asynccontextmanager
import asyncio
import ipaddress
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio
from curl_cffi.requests import AsyncSession
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient

import novelwiki.db.connection as db_connection
from novelwiki.api import routes
from novelwiki.db.connection import close_db_pool, get_db_pool
from novelwiki.db.schema import init_database
from novelwiki.scraper import safe_fetch
from novelwiki.scraper.runner import scrape_source
from novelwiki.modules.identity.adapters.outbound.postgres_auth import PostgresAuthPersistence
from novelwiki.platform.config import settings


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


@asynccontextmanager
async def _source_client(user):
    """Real cookie authentication and HTTP validation; no lifespan/providers."""
    from novelwiki.api.app import app

    pool = await get_db_pool()
    token = await PostgresAuthPersistence(pool).create_user_session(user["id"], "source-regression")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://testserver",
        cookies={settings.SESSION_COOKIE: token, settings.CSRF_COOKIE: "source-regression-csrf"},
        headers={"X-Tideglass-Request": "1", "X-Tideglass-CSRF": "source-regression-csrf"},
    ) as client:
        yield client


async def _source_state(source_id):
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        row = await connection.fetchrow("SELECT * FROM sources WHERE id=$1", source_id)
        chapters = await connection.fetch(
            "SELECT number,title,content FROM chapters WHERE source_id=$1 ORDER BY number", source_id,
        )
    source = dict(row)
    if isinstance(source["config"], str):
        source["config"] = json.loads(source["config"])
    return source, [dict(chapter) for chapter in chapters]


async def _seed_source_configuration(scraper_db):
    initial = {
        "archive_password": "fixture-old-secret", "content_selector": ".reader",
        "allowed_hosts": ["assets.example.test"], "options": {"retry": 3},
    }
    pool = await get_db_pool()
    async with pool.acquire() as connection:
        await connection.execute(
            "UPDATE sources SET config=$1::jsonb WHERE id=$2", json.dumps(initial), scraper_db["source_a"],
        )
        await connection.execute(
            "INSERT INTO chapters (novel_id,source_id,number,title,content) VALUES ($1,$2,1,'Chapter 1','Synthetic prose.')",
            scraper_db["novel_a"], scraper_db["source_a"],
        )
    return initial


@pytest.mark.asyncio
async def test_source_config_patch_merges_and_password_is_not_in_novel_details(scraper_db):
    initial = await _seed_source_configuration(scraper_db)
    path = f'/api/novels/{scraper_db["novel_a"]}/sources/{scraper_db["source_a"]}'
    async with _source_client(scraper_db["owner_a"]) as client:
        response = await client.patch(path, json={"config": {"archive_password": "fixture-new-secret"}, "label": "Updated label"})
        assert response.status_code == 200
        assert "fixture-new-secret" not in response.text
    source, chapters = await _source_state(scraper_db["source_a"])
    assert source["config"] == {**initial, "archive_password": "fixture-new-secret"}
    assert source["label"] == "Updated label"
    assert float(chapters[0]["number"]) == 1

    pool = await get_db_pool()
    async with pool.acquire() as connection:
        await connection.execute("UPDATE novels SET visibility='public' WHERE id=$1", scraper_db["novel_a"])
    for viewer in (scraper_db["owner_a"], scraper_db["owner_b"]):
        async with _source_client(viewer) as client:
            response = await client.get(f'/api/novels/{scraper_db["novel_a"]}')
        assert response.status_code == 200
        assert response.json()["sources"]
        assert all("config" not in source for source in response.json()["sources"])
        assert "fixture-new-secret" not in response.text


@pytest.mark.asyncio
async def test_source_empty_config_patch_preserves_keys_and_empty_password_clears_only_password(scraper_db):
    initial = await _seed_source_configuration(scraper_db)
    path = f'/api/novels/{scraper_db["novel_a"]}/sources/{scraper_db["source_a"]}'
    async with _source_client(scraper_db["owner_a"]) as client:
        assert (await client.patch(path, json={"config": {}})).status_code == 200
        assert (await _source_state(scraper_db["source_a"]))[0]["config"] == initial
        assert (await client.patch(path, json={"config": {"archive_password": ""}})).status_code == 200
    assert (await _source_state(scraper_db["source_a"]))[0]["config"] == {**initial, "archive_password": ""}


@pytest.mark.asyncio
@pytest.mark.parametrize("target,public,status", [("foreign_source", False, 404), ("foreign_novel", False, 404), ("foreign_novel", True, 403)])
async def test_source_config_patch_respects_source_novel_and_owner(scraper_db, target, public, status):
    novel = scraper_db["novel_a"] if target == "foreign_source" else scraper_db["novel_b"]
    if public:
        pool = await get_db_pool()
        async with pool.acquire() as connection:
            await connection.execute("UPDATE novels SET visibility='public' WHERE id=$1", novel)
    before = await _source_state(scraper_db["source_b"])
    async with _source_client(scraper_db["owner_a"]) as client:
        response = await client.patch(
            f'/api/novels/{novel}/sources/{scraper_db["source_b"]}',
            json={"config": {"archive_password": "fixture-attacker-change"}, "chapter_offset": 10},
        )
    assert response.status_code == status
    assert await _source_state(scraper_db["source_b"]) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [
    None, [], "invalid", {"retry": float("nan")}, {"retry": float("inf")},
    {"archive_password": 123}, {"archive_password": None},
    {"nested": ["bad\x00value"]}, {"bad\x00key": "value"}, {"nested": {"value": "\ud800"}},
])
async def test_invalid_source_config_does_not_renumber_or_write_other_fields(scraper_db, config):
    await _seed_source_configuration(scraper_db)
    before = await _source_state(scraper_db["source_a"])
    async with _source_client(scraper_db["owner_a"]) as client:
        response = await client.patch(
            f'/api/novels/{scraper_db["novel_a"]}/sources/{scraper_db["source_a"]}',
            content=json.dumps({"config": config, "chapter_offset": 10, "label": "Must not persist"}),
            headers={"Content-Type": "application/json"},
        )
    assert await _source_state(scraper_db["source_a"]) == before
    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("offset", [None, "NaN", "Infinity", float("nan"), float("inf"), -float("inf")])
async def test_invalid_source_offset_does_not_change_config_or_chapters(scraper_db, offset):
    await _seed_source_configuration(scraper_db)
    before = await _source_state(scraper_db["source_a"])
    async with _source_client(scraper_db["owner_a"]) as client:
        response = await client.patch(
            f'/api/novels/{scraper_db["novel_a"]}/sources/{scraper_db["source_a"]}',
            content=json.dumps({"chapter_offset": offset, "config": {"archive_password": "Must not persist"}}),
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 422
    assert await _source_state(scraper_db["source_a"]) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("maximum", [0, -1, 1.5, "NaN"])
async def test_invalid_scrape_maximum_does_not_create_job(scraper_db, maximum):
    pool = await get_db_pool()
    before = await pool.fetchval("SELECT COUNT(*) FROM jobs")
    async with _source_client(scraper_db["owner_a"]) as client:
        response = await client.post(
            f'/api/novels/{scraper_db["novel_a"]}/scrape',
            json={"source_id": scraper_db["source_a"], "max_chapters": maximum},
        )
    assert response.status_code == 422
    assert await pool.fetchval("SELECT COUNT(*) FROM jobs") == before


@pytest.mark.asyncio
async def test_source_config_and_finite_offset_can_be_updated_together(scraper_db):
    initial = await _seed_source_configuration(scraper_db)
    async with _source_client(scraper_db["owner_a"]) as client:
        response = await client.patch(
            f'/api/novels/{scraper_db["novel_a"]}/sources/{scraper_db["source_a"]}',
            json={"chapter_offset": 0.5, "config": {"archive_password": "fixture-new-secret"}},
        )
    assert response.status_code == 200 and response.json()["renumbered"] == 1
    source, chapters = await _source_state(scraper_db["source_a"])
    assert source["config"] == {**initial, "archive_password": "fixture-new-secret"}
    assert float(source["chapter_offset"]) == 0.5
    assert float(chapters[0]["number"]) == 1.5


@pytest.mark.asyncio
@pytest.mark.parametrize("extra", [
    {"chapter_offset": "NaN"}, {"chapter_offset": float("inf")},
    {"config": {"retry": float("nan")}}, {"config": {"archive_password": []}},
])
async def test_source_create_rejects_invalid_offset_or_config_without_insert(scraper_db, extra):
    pool = await get_db_pool()
    before = await pool.fetchval("SELECT COUNT(*) FROM sources")
    async with _source_client(scraper_db["owner_a"]) as client:
        response = await client.post(
            f'/api/novels/{scraper_db["novel_a"]}/sources',
            content=json.dumps({"adapter": "raw-fucknovelpia", "start_url": "https://public.example/novel/synthetic", **extra}),
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 422
    assert await pool.fetchval("SELECT COUNT(*) FROM sources") == before


@pytest.mark.asyncio
@pytest.mark.parametrize("field,value", [
    ("label", "bad\x00label"), ("label", "bad\ud800label"),
    ("language", "en\x00"), ("language", "en\ud800"),
    ("start_url", "https://public.example/bad\x00path"),
    ("start_url", "https://public.example/bad\ud800path"),
])
async def test_invalid_source_text_does_not_renumber_or_update_config(scraper_db, field, value):
    await _seed_source_configuration(scraper_db)
    before = await _source_state(scraper_db["source_a"])
    async with _source_client(scraper_db["owner_a"]) as client:
        response = await client.patch(
            f'/api/novels/{scraper_db["novel_a"]}/sources/{scraper_db["source_a"]}',
            content=json.dumps({field: value, "chapter_offset": 10, "config": {"archive_password": "Must not persist"}}),
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 422
    assert await _source_state(scraper_db["source_a"]) == before


@pytest.mark.asyncio
async def test_existing_nullable_source_fields_remain_nullable(scraper_db):
    async with _source_client(scraper_db["owner_a"]) as client:
        response = await client.patch(
            f'/api/novels/{scraper_db["novel_a"]}/sources/{scraper_db["source_a"]}',
            json={"start_url": None, "label": None, "language": None, "is_raw": None},
        )
    assert response.status_code == 200
    source, _ = await _source_state(scraper_db["source_a"])
    assert all(source[field] is None for field in ("start_url", "label", "language", "is_raw"))


@pytest.mark.asyncio
@pytest.mark.parametrize("source_fields", [
    {"config": {"archive_password": 123}}, {"config": {"retry": float("nan")}},
    {"config": {"nested": ["bad\x00value"]}}, {"label": "bad\ud800label"},
])
async def test_new_novel_with_invalid_source_rolls_back_every_created_row(scraper_db, monkeypatch, source_fields):
    async def public_dns(_host, _port):
        return [ipaddress.ip_address("8.8.8.8")]

    monkeypatch.setattr(safe_fetch, "_resolve_host", public_dns)
    pool = await get_db_pool()

    async def counts():
        return tuple([await pool.fetchval(f"SELECT COUNT(*) FROM {table}") for table in ("novels", "sources", "library_entries")])

    before = await counts()
    async with _source_client(scraper_db["owner_a"]) as client:
        response = await client.post(
            "/api/novels",
            content=json.dumps({
                "title": "Must not leave a novel behind",
                "source": {"adapter": "raw-fucknovelpia", "start_url": "https://public.example/novel/synthetic", **source_fields},
            }),
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 422
    assert await counts() == before
