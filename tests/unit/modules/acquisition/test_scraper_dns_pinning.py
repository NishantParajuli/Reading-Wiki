from __future__ import annotations

import asyncio
import ipaddress
from contextlib import asynccontextmanager

import pytest
from curl_cffi import CurlOpt
from curl_cffi.requests import AsyncSession

from novelwiki.modules.acquisition.adapters.outbound.scraper import safe_fetch


class _Response:
    primary_ip = "8.8.8.8"
    status_code = 200
    headers = {}
    url = "https://public.example/chapter"

    async def aiter_content(self):
        yield b"chapter text"


class _Session:
    def __init__(self):
        self.curl_options = {CurlOpt.TIMEOUT: 10}
        self.requests = []

    @asynccontextmanager
    async def stream(self, method, url, **kwargs):
        self.requests.append((url, dict(self.curl_options)))
        yield _Response()


@pytest.mark.asyncio
async def test_fetch_pins_validated_dns_and_restores_session_options(monkeypatch):
    async def resolve(_host, _port):
        return [ipaddress.ip_address("8.8.8.8"), ipaddress.ip_address("2606:4700:4700::1111")]

    monkeypatch.setattr(safe_fetch, "_resolve_host", resolve)
    session = _Session()
    original = session.curl_options

    response = await safe_fetch.safe_fetch(session, "https://public.example/chapter")

    assert response.body == b"chapter text"
    options = session.requests[0][1]
    assert options[CurlOpt.RESOLVE] == ["public.example:443:8.8.8.8,[2606:4700:4700::1111]"]
    assert options[CurlOpt.PROXY] == ""
    assert options[CurlOpt.FRESH_CONNECT] == 1
    assert session.curl_options is original


@pytest.mark.asyncio
async def test_failed_fetch_restores_session_options(monkeypatch):
    async def resolve(_host, _port):
        return [ipaddress.ip_address("8.8.8.8")]

    monkeypatch.setattr(safe_fetch, "_resolve_host", resolve)
    session = _Session()
    original = session.curl_options

    with pytest.raises(safe_fetch.ResponseTooLargeError):
        await safe_fetch.safe_fetch(session, "https://public.example/chapter", max_bytes=1)

    assert session.curl_options is original


@pytest.mark.asyncio
async def test_real_curl_uses_pinned_address_without_resolving_hostname(monkeypatch):
    requests = []

    async def handle(reader, writer):
        requests.append(await reader.readuntil(b"\r\n\r\n"))
        writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok")
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    async def resolve(host, requested_port):
        assert host == "pinned-scraper.invalid"
        assert requested_port == port
        return [ipaddress.ip_address("127.0.0.1")]

    # Only the address guard is relaxed: real curl must use the resolved address
    # while retaining an otherwise unresolvable HTTP hostname.
    monkeypatch.setattr(safe_fetch, "_resolve_host", resolve)
    monkeypatch.setattr(safe_fetch, "_ensure_public_ip", lambda _ip: None)
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:1")
    try:
        async with AsyncSession() as session:
            response = await safe_fetch.safe_fetch(
                session, f"http://pinned-scraper.invalid:{port}/chapter", timeout=2,
                impersonate=None,
            )
            assert session.curl_options == {}
    finally:
        server.close()
        await server.wait_closed()

    assert response.body == b"ok"
    assert f"Host: pinned-scraper.invalid:{port}".encode() in requests[0]


@pytest.mark.asyncio
async def test_concurrent_fetches_keep_their_own_dns_options(monkeypatch):
    async def resolve(host, _port):
        return [ipaddress.ip_address("8.8.8.8" if host == "one.example" else "1.1.1.1")]

    class YieldingSession(_Session):
        @asynccontextmanager
        async def stream(self, method, url, **kwargs):
            before = dict(self.curl_options)
            await asyncio.sleep(0)
            assert self.curl_options == before
            self.requests.append((url, before))
            yield _Response()

    monkeypatch.setattr(safe_fetch, "_resolve_host", resolve)
    session = YieldingSession()
    await asyncio.gather(
        safe_fetch.safe_fetch(session, "https://one.example/chapter"),
        safe_fetch.safe_fetch(session, "https://two.example/chapter"),
    )

    assert [options[CurlOpt.RESOLVE] for _, options in session.requests] == [
        ["one.example:443:8.8.8.8"], ["two.example:443:1.1.1.1"],
    ]
