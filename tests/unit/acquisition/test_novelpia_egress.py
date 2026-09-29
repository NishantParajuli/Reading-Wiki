"""Security boundary tests for the browser's only outbound network route."""

import asyncio
import importlib.util
from pathlib import Path
import socket
from unittest.mock import AsyncMock, Mock

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "novelpia_egress", Path(__file__).parents[3] / "sidecar-novelpia-egress/proxy.py")
proxy = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(proxy)


@pytest.mark.parametrize("address", [
    "127.0.0.1", "10.1.2.3", "172.16.1.1", "192.168.1.1", "169.254.169.254",
    "0.0.0.0", "100.100.100.200", "192.0.2.1", "224.0.0.1", "240.0.0.1",
    "255.255.255.255", "::", "::1", "fc00::1", "fe80::1", "ff02::1",
    "2001:db8::1", "::ffff:127.0.0.1", "::ffff:8.8.8.8",
    "64:ff9b::7f00:1", "2002:7f00:1::", "2001::1", "2606:4700::1%eth0",
])
def test_non_public_and_transition_addresses_are_rejected(address):
    assert not proxy.public_address(address)


@pytest.mark.parametrize("address", ["8.8.8.8", "93.184.216.34", "2606:4700:4700::1111"])
def test_public_addresses(address):
    assert proxy.public_address(address)


@pytest.mark.parametrize("target", [
    "localhost:80", "example.com:22", "user@example.com:443", "example.com:0443",
    "example.com:443/path", "example.com:443?x=y", "example.com%00:443",
    "example.com\\evil:443", "a..com:443", "-a.com:443", "[::1%eth0]:443",
    "[::1]:443:443", "éxample.com:443", "example.com:443\nHost:evil",
])
def test_ambiguous_or_non_https_authorities_rejected(target):
    with pytest.raises(proxy.Rejected):
        proxy.authority(target)


@pytest.mark.parametrize("wire_request", [
    b"GET https://example.com/ HTTP/1.1\r\n\r\n",
    b"CONNECT example.com:443 HTTP/2\r\n\r\n",
    b"CONNECT example.com:443 HTTP/1.1\r\nHost: other.com:443\r\n\r\n",
    b"CONNECT example.com:443 HTTP/1.1\r\nContent-Length: 1\r\n\r\n",
    b"CONNECT example.com:443 HTTP/1.1\r\nTransfer-Encoding: chunked\r\n\r\n",
    b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\nHost: example.com:443\r\n\r\n",
    b"CONNECT example.com:443 HTTP/1.1\r\nX: value\x00evil\r\n\r\n",
    b"CONNECT example.com:443 HTTP/1.1\r\n folded: header\r\n\r\n",
    b"CONNECT example.com:443 HTTP/1.1\r\nX: " + b"x" * 8192 + b"\r\n\r\n",
])
def test_http_request_smuggling_and_oversized_headers_rejected(wire_request):
    with pytest.raises(proxy.Rejected):
        proxy.parse_request(wire_request)


def test_connect_request_only_returns_destination_not_proxy_credentials():
    assert proxy.parse_request(
        b"CONNECT Example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n"
        b"Proxy-Authorization: private-test-value\r\n\r\n") == ("example.com", 443)


def record(address, family=socket.AF_INET):
    target = (address, 443) if family == socket.AF_INET else (address, 443, 0, 0)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", target)


@pytest.mark.asyncio
async def test_mixed_public_and_private_dns_answer_fails_entire_request(monkeypatch):
    lookup = AsyncMock(return_value=[record("8.8.8.8"), record("127.0.0.1")])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    with pytest.raises(proxy.Rejected) as error:
        await proxy.resolve_public("mixed.example", 443)
    assert error.value.status == 403


@pytest.mark.asyncio
async def test_dns_timeout_fails_closed(monkeypatch):
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo",
                        AsyncMock(side_effect=TimeoutError))
    with pytest.raises(proxy.Rejected) as error:
        await proxy.resolve_public("slow.example", 443)
    assert error.value.status == 502


@pytest.mark.asyncio
async def test_timed_out_dns_retains_slot_until_real_lookup_finishes(monkeypatch):
    pending = asyncio.Event()
    started = 0

    async def stuck_lookup(*args, **kwargs):
        nonlocal started
        started += 1
        await pending.wait()
        return [record("8.8.8.8")]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", stuck_lookup)
    monkeypatch.setattr(proxy, "DNS_SECONDS", 0.01)
    results = await asyncio.gather(*[
        proxy.resolve_public("slow.example", 443) for _ in range(12)
    ], return_exceptions=True)
    assert all(isinstance(result, proxy.Rejected) for result in results)
    assert started == 8
    # Timed-out clients cannot add more DNS work while those eight are stuck.
    with pytest.raises(proxy.Rejected):
        await proxy.resolve_public("another.example", 443)
    assert started == 8
    pending.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert await proxy.resolve_public("recovered.example", 443)


@pytest.mark.asyncio
async def test_connection_is_pinned_to_once_resolved_numeric_address(monkeypatch):
    loop = asyncio.get_running_loop()
    lookup = AsyncMock(return_value=[record("93.184.216.34")])
    connect = AsyncMock()
    fake_socket = Mock()
    streams = (Mock(), Mock())
    monkeypatch.setattr(loop, "getaddrinfo", lookup)
    monkeypatch.setattr(loop, "sock_connect", connect)
    monkeypatch.setattr(proxy.socket, "socket", Mock(return_value=fake_socket))
    monkeypatch.setattr(asyncio, "open_connection", AsyncMock(return_value=streams))
    assert await proxy.connect_public("rebind.example", 443) == streams
    lookup.assert_awaited_once()
    connect.assert_awaited_once_with(fake_socket, ("93.184.216.34", 443))
    asyncio.open_connection.assert_awaited_once_with(sock=fake_socket)


@pytest.mark.asyncio
async def test_failed_connection_closes_socket(monkeypatch):
    fake_socket = Mock()
    monkeypatch.setattr(proxy, "resolve_public", AsyncMock(return_value=[
        (socket.AF_INET, ("8.8.8.8", 443))]))
    monkeypatch.setattr(proxy.socket, "socket", Mock(return_value=fake_socket))
    monkeypatch.setattr(asyncio.get_running_loop(), "sock_connect", AsyncMock(side_effect=OSError))
    with pytest.raises(proxy.Rejected):
        await proxy.connect_public("fail.example", 443)
    fake_socket.close.assert_called_once()


@pytest.mark.asyncio
async def test_tunnel_volume_is_bounded(monkeypatch):
    monkeypatch.setattr(proxy, "MAX_TUNNEL_BYTES", 3)
    first = asyncio.StreamReader()
    first.feed_data(b"1234")
    second = asyncio.StreamReader()
    writer = Mock(drain=AsyncMock())
    with pytest.raises(proxy.Rejected) as error:
        await proxy.relay(first, writer, second, writer)
    assert error.value.status == 413
    writer.write.assert_not_called()


@pytest.mark.asyncio
async def test_proxy_refuses_private_destination_before_connecting(monkeypatch):
    lookup = AsyncMock(return_value=[record("169.254.169.254")])
    connect = AsyncMock()
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", lookup)
    monkeypatch.setattr(asyncio.get_running_loop(), "sock_connect", connect)
    reader = asyncio.StreamReader()
    reader.feed_data(b"CONNECT metadata.example:443 HTTP/1.1\r\n\r\n")
    writer = Mock(wait_closed=AsyncMock())
    server = proxy.Proxy()
    await server.handle(reader, writer)
    connect.assert_not_awaited()
    assert b"403" in writer.write.call_args.args[0]
    assert server.active == 0


@pytest.mark.asyncio
async def test_connection_limit_rejects_without_dns_or_read(monkeypatch):
    reader = Mock(readuntil=AsyncMock())
    writer = Mock(wait_closed=AsyncMock())
    connect = AsyncMock()
    monkeypatch.setattr(proxy, "connect_public", connect)
    server = proxy.Proxy()
    server.active = proxy.MAX_CONNECTIONS
    await server.handle(reader, writer)
    assert b"429" in writer.write.call_args.args[0]
    reader.readuntil.assert_not_awaited()
    connect.assert_not_awaited()
    assert server.active == proxy.MAX_CONNECTIONS
