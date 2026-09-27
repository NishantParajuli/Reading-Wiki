"""Bounded HTTPS CONNECT egress for an otherwise network-isolated browser.

Only this process resolves destination names. Every result must be public, and
the subsequent socket connects to that checked numeric address, never the name.
No destination, request header, credential, or payload is logged.
"""

import asyncio
import concurrent.futures
import ipaddress
import re
import socket
import weakref

HEADER_BYTES = 8192
MAX_CONNECTIONS = 96
MAX_TUNNEL_BYTES = 64 * 1024 * 1024
DNS_SECONDS = 5
CONNECT_SECONDS = 10
HEADER_SECONDS = 10
IDLE_SECONDS = 30
TUNNEL_SECONDS = 120
_LABEL = re.compile(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\Z")
_HEADER_NAME = re.compile(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+\Z")
_TRANSITION_NETWORKS = tuple(map(ipaddress.ip_network, (
    "64:ff9b::/96", "64:ff9b:1::/48", "2001::/32", "2002::/16",
)))
_DNS_SLOTS = weakref.WeakKeyDictionary()


class Rejected(Exception):
    def __init__(self, status=400):
        self.status = status


def public_address(value):
    """Reject non-public addresses and IPv6 mechanisms embedding another IP."""
    address = ipaddress.ip_address(value)
    if (not address.is_global or address.is_multicast or address.is_reserved
            or address.is_loopback or address.is_link_local or address.is_unspecified):
        return False
    if isinstance(address, ipaddress.IPv6Address):
        if address.ipv4_mapped or address.scope_id:
            return False
        if any(address in network for network in _TRANSITION_NETWORKS):
            return False
    return True


def authority(value):
    if not value or any(char in value for char in "@/%?#\\ \t\r\n"):
        raise Rejected()
    if value.startswith("["):
        match = re.fullmatch(r"\[([0-9a-fA-F:]+)\]:443", value)
        if not match:
            raise Rejected()
        try:
            host = str(ipaddress.IPv6Address(match[1]))
        except ValueError:
            raise Rejected() from None
    else:
        if value.count(":") != 1:
            raise Rejected()
        host, port = value.split(":")
        if port != "443":
            raise Rejected(403)
        host = host.lower().rstrip(".")
        if len(host) > 253 or not all(_LABEL.fullmatch(part) for part in host.split(".")):
            raise Rejected()
    return host, 443


def parse_request(data):
    if len(data) > HEADER_BYTES or not data.endswith(b"\r\n\r\n"):
        raise Rejected(431)
    lines = data[:-4].split(b"\r\n")
    try:
        method, target, version = lines[0].decode("ascii").split(" ")
    except (ValueError, UnicodeError):
        raise Rejected() from None
    if method != "CONNECT":
        raise Rejected(405)
    if version not in ("HTTP/1.0", "HTTP/1.1"):
        raise Rejected()
    destination = authority(target)
    seen = set()
    for line in lines[1:]:
        name, separator, raw_value = line.partition(b":")
        if not separator or not _HEADER_NAME.fullmatch(name):
            raise Rejected()
        if any(byte < 32 and byte != 9 or byte == 127 for byte in raw_value):
            raise Rejected()
        name = name.lower()
        if name in seen:
            raise Rejected()
        seen.add(name)
        if name == b"transfer-encoding":
            raise Rejected()
        if name == b"content-length" and raw_value.strip() != b"0":
            raise Rejected()
        if name == b"host":
            try:
                if authority(raw_value.strip().decode("ascii")) != destination:
                    raise Rejected()
            except UnicodeError:
                raise Rejected() from None
    return destination


async def resolve_public(host, port):
    loop = asyncio.get_running_loop()
    slots = _DNS_SLOTS.setdefault(loop, asyncio.Semaphore(8))
    try:
        async with asyncio.timeout(DNS_SECONDS):
            await slots.acquire()
            # libc DNS cannot reliably be interrupted. Hold its slot until the
            # actual lookup finishes, even if this request times out, so stuck
            # resolvers cannot create an unbounded executor work queue.
            lookup = asyncio.create_task(loop.getaddrinfo(
                host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM,
                proto=socket.IPPROTO_TCP,
            ))

            def lookup_finished(task):
                slots.release()
                if not task.cancelled():
                    task.exception()  # Consume late errors after request timeout.

            lookup.add_done_callback(lookup_finished)
            records = await asyncio.shield(lookup)
    except (OSError, TimeoutError):
        raise Rejected(502) from None
    if not records or len(records) > 64:
        raise Rejected(403)
    checked = []
    for family, socktype, protocol, _, address in records:
        try:
            safe = (family in (socket.AF_INET, socket.AF_INET6)
                    and socktype == socket.SOCK_STREAM
                    and protocol == socket.IPPROTO_TCP
                    and address[1] == port and public_address(address[0])
                    and (family != socket.AF_INET6 or address[3] == 0))
        except (ValueError, IndexError):
            safe = False
        if not safe:
            raise Rejected(403)
        entry = (family, address)
        if entry not in checked:
            checked.append(entry)
    return checked


async def connect_public(host, port):
    addresses = await resolve_public(host, port)
    loop = asyncio.get_running_loop()
    # A single overall timeout prevents a large DNS answer extending the budget.
    try:
        async with asyncio.timeout(CONNECT_SECONDS):
            for family, address in addresses:
                sock = socket.socket(family, socket.SOCK_STREAM, socket.IPPROTO_TCP)
                sock.setblocking(False)
                try:
                    # inet_pton confirms numeric input; sock_connect therefore does
                    # not perform a second lookup that could rebind to a private IP.
                    socket.inet_pton(family, address[0])
                    await loop.sock_connect(sock, address)
                    return await asyncio.open_connection(sock=sock)
                except OSError:
                    sock.close()
                except BaseException:
                    sock.close()
                    raise
    except TimeoutError:
        pass
    raise Rejected(502)


async def relay(client_reader, client_writer, remote_reader, remote_writer):
    transferred = 0

    async def pump(reader, writer):
        nonlocal transferred
        while data := await asyncio.wait_for(reader.read(65536), IDLE_SECONDS):
            transferred += len(data)
            if transferred > MAX_TUNNEL_BYTES:
                raise Rejected(413)
            writer.write(data)
            await asyncio.wait_for(writer.drain(), IDLE_SECONDS)

    tasks = [asyncio.create_task(pump(client_reader, remote_writer)),
             asyncio.create_task(pump(remote_reader, client_writer))]
    try:
        async with asyncio.timeout(TUNNEL_SECONDS):
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def close(writer):
    writer.close()
    try:
        await asyncio.wait_for(writer.wait_closed(), 2)
    except (OSError, TimeoutError):
        pass


class Proxy:
    def __init__(self):
        self.active = 0

    async def handle(self, reader, writer):
        remote_writer = None
        established = False
        admitted = False
        try:
            if self.active >= MAX_CONNECTIONS:
                raise Rejected(429)
            self.active += 1
            admitted = True
            try:
                data = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), HEADER_SECONDS)
            except asyncio.LimitOverrunError:
                raise Rejected(431) from None
            host, port = parse_request(data)
            remote_reader, remote_writer = await connect_public(host, port)
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await asyncio.wait_for(writer.drain(), IDLE_SECONDS)
            established = True
            await relay(reader, writer, remote_reader, remote_writer)
        except Rejected as error:
            if not established:
                writer.write(f"HTTP/1.1 {error.status} Rejected\r\nConnection: close\r\nContent-Length: 0\r\n\r\n".encode("ascii"))
        except (OSError, TimeoutError, asyncio.IncompleteReadError):
            pass
        finally:
            if admitted:
                self.active -= 1
            if remote_writer is not None:
                await close(remote_writer)
            await close(writer)


async def main():
    asyncio.get_running_loop().set_default_executor(
        concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="dns"))
    proxy = Proxy()
    server = await asyncio.start_server(proxy.handle, "0.0.0.0", 8899,
                                        limit=HEADER_BYTES, backlog=MAX_CONNECTIONS)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
