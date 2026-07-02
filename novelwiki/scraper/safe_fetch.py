from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import socket
from dataclasses import dataclass
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin, urlsplit, urlunsplit

from curl_cffi.requests import AsyncSession

from novelwiki.config.settings import settings

logger = logging.getLogger(__name__)

_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_DEFAULT_MAX_REDIRECTS = 5
_CHARSET_RE = re.compile(r"charset=([A-Za-z0-9._-]+)", re.IGNORECASE)


class SafeFetchError(ValueError):
    """Base class for scraper fetch failures that should not be retried blindly."""


class UnsafeUrlError(SafeFetchError):
    """Raised when a scraper URL targets a disallowed scheme, host, or address."""


class ResponseTooLargeError(SafeFetchError):
    """Raised when a scraper response exceeds the configured body limit."""


class FetchHTTPError(SafeFetchError):
    """Raised for non-success HTTP responses after URL validation succeeds."""

    def __init__(self, status_code: int, url: str):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code} from {describe_url(url)}")


@dataclass(frozen=True)
class ValidatedUrl:
    url: str
    host: str
    port: int
    ips: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]


@dataclass(frozen=True)
class SafeFetchResponse:
    url: str
    status_code: int
    headers: Mapping[str, str]
    body: bytes

    def text(self, encoding: str | None = None) -> str:
        chosen = encoding or _charset_from_headers(self.headers) or "utf-8"
        return self.body.decode(chosen, errors="replace")

    def json(self) -> Any:
        return json.loads(self.text())


def describe_url(url: str) -> str:
    """Log-safe URL summary: scheme + host only, never credentials/query/path."""
    try:
        parsed = urlsplit(url)
        host = parsed.hostname or "<missing-host>"
        scheme = parsed.scheme or "<missing-scheme>"
        if parsed.port:
            return f"{scheme}://{host}:{parsed.port}"
        return f"{scheme}://{host}"
    except Exception:
        return "<invalid-url>"


def parse_allowed_hosts(raw: str | Iterable[str] | None) -> set[str]:
    if raw is None:
        return set()
    if isinstance(raw, str):
        parts = raw.split(",")
    else:
        parts = raw
    out: set[str] = set()
    for part in parts:
        host = (part or "").strip()
        if not host:
            continue
        try:
            out.add(_normalize_host(host))
        except UnsafeUrlError:
            logger.warning("Ignoring invalid scraper allowed-host override: %r", host)
    return out


def host_from_url(url: str) -> str:
    parsed = urlsplit((url or "").strip())
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        raise UnsafeUrlError("URL must be absolute HTTP(S) with a host.")
    return _normalize_host(parsed.hostname)


async def validate_source_start_url(url: str) -> str:
    """Validate and normalize a user-provided scraper start URL before it is stored."""
    validated = await validate_url(url, require_same_host=False)
    return validated.url


async def validate_url(
    url: str,
    *,
    source_host: str | None = None,
    allowed_hosts: Iterable[str] | None = None,
    require_same_host: bool | None = None,
) -> ValidatedUrl:
    if not isinstance(url, str) or not url.strip():
        raise UnsafeUrlError("URL is required.")

    parsed = urlsplit(url.strip())
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise UnsafeUrlError("Only http and https scraper URLs are allowed.")
    if not parsed.hostname:
        raise UnsafeUrlError("URL must include a host.")
    if parsed.username is not None or parsed.password is not None:
        raise UnsafeUrlError("URLs with embedded credentials are not allowed.")

    host = _normalize_host(parsed.hostname)
    try:
        explicit_port = parsed.port
    except ValueError as exc:
        raise UnsafeUrlError("URL port is invalid.") from exc
    port = explicit_port or (443 if scheme == "https" else 80)
    if port <= 0 or port > 65535:
        raise UnsafeUrlError("URL port is invalid.")

    same_host_required = settings.SCRAPER_REQUIRE_SAME_HOST if require_same_host is None else require_same_host
    if same_host_required and source_host:
        permitted = parse_allowed_hosts(allowed_hosts)
        permitted.update(parse_allowed_hosts(settings.SCRAPER_ALLOWED_HOST_OVERRIDES))
        permitted.add(_normalize_host(source_host))
        if host not in permitted:
            raise UnsafeUrlError("URL host is outside this source's allowed host set.")

    ips = await _resolve_host(host, port)
    for ip in ips:
        _ensure_public_ip(ip)

    normalized_url = _normalize_url(parsed, host, explicit_port, port)
    return ValidatedUrl(
        url=normalized_url,
        host=host,
        port=port,
        ips=tuple(ips),
    )


async def safe_fetch(
    session: AsyncSession,
    url: str,
    *,
    source_host: str | None = None,
    allowed_hosts: Iterable[str] | None = None,
    require_same_host: bool | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: float | None = None,
    max_bytes: int | None = None,
    max_redirects: int = _DEFAULT_MAX_REDIRECTS,
    impersonate: str | None = "chrome",
) -> SafeFetchResponse:
    current_url = url
    timeout = float(timeout if timeout is not None else settings.SCRAPER_TIMEOUT_SECONDS)
    max_bytes = int(max_bytes if max_bytes is not None else settings.SCRAPER_MAX_RESPONSE_MB * 1024 * 1024)

    for _ in range(max_redirects + 1):
        validated = await validate_url(
            current_url,
            source_host=source_host,
            allowed_hosts=allowed_hosts,
            require_same_host=require_same_host,
        )
        request_kwargs: dict[str, Any] = {
            "headers": dict(headers or {}),
            "timeout": timeout,
            "allow_redirects": False,
            "impersonate": impersonate,
        }

        async with session.stream("GET", validated.url, **request_kwargs) as resp:
            primary_ip = getattr(resp, "primary_ip", "")
            if primary_ip:
                _ensure_public_ip(ipaddress.ip_address(primary_ip))

            if resp.status_code in _REDIRECT_STATUSES:
                location = resp.headers.get("location") or resp.headers.get("Location")
                if not location:
                    raise FetchHTTPError(resp.status_code, validated.url)
                current_url = urljoin(validated.url, location)
                continue

            if resp.status_code >= 400:
                raise FetchHTTPError(resp.status_code, validated.url)

            body = await _read_limited(resp, max_bytes)
            response_url = getattr(resp, "url", "") or validated.url
            return SafeFetchResponse(
                url=response_url,
                status_code=int(resp.status_code),
                headers=_headers_to_plain_dict(resp.headers),
                body=body,
            )

    raise UnsafeUrlError("Too many redirects while fetching scraper URL.")


async def safe_fetch_text(
    session: AsyncSession,
    url: str,
    *,
    encoding: str | None = None,
    **kwargs: Any,
) -> str:
    response = await safe_fetch(session, url, **kwargs)
    return response.text(encoding=encoding)


async def safe_fetch_json(session: AsyncSession, url: str, **kwargs: Any) -> Any:
    response = await safe_fetch(session, url, **kwargs)
    return response.json()


async def safe_fetch_bytes(session: AsyncSession, url: str, **kwargs: Any) -> bytes:
    response = await safe_fetch(session, url, **kwargs)
    return response.body


async def _read_limited(resp: Any, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    async for chunk in resp.aiter_content():
        total += len(chunk)
        if total > max_bytes:
            raise ResponseTooLargeError(f"Scraper response exceeded {max_bytes} bytes.")
        chunks.append(chunk)
    return b"".join(chunks)


async def _resolve_host(host: str, port: int) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass

    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise UnsafeUrlError("Could not resolve scraper URL host.") from exc

    ips = sorted({info[4][0] for info in infos})
    if not ips:
        raise UnsafeUrlError("Scraper URL host resolved to no addresses.")
    try:
        return [ipaddress.ip_address(ip) for ip in ips]
    except ValueError as exc:
        raise UnsafeUrlError("Scraper URL host resolved to an invalid address.") from exc


def _normalize_host(host: str) -> str:
    raw = (host or "").strip().rstrip(".").lower()
    if not raw:
        raise UnsafeUrlError("URL host is missing.")
    if any(c.isspace() for c in raw) or "/" in raw or "\\" in raw or "@" in raw:
        raise UnsafeUrlError("URL host is invalid.")
    if raw == "localhost" or raw.endswith(".localhost"):
        raise UnsafeUrlError("Localhost scraper URLs are not allowed.")

    try:
        return ipaddress.ip_address(raw).compressed.lower()
    except ValueError:
        pass

    if "%" in raw:
        raise UnsafeUrlError("URL host is invalid.")
    try:
        ascii_host = raw.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise UnsafeUrlError("URL host is invalid.") from exc
    labels = ascii_host.split(".")
    if any(not label for label in labels):
        raise UnsafeUrlError("URL host is invalid.")
    return ascii_host


def _normalize_url(parsed: Any, host: str, explicit_port: int | None, resolved_port: int) -> str:
    try:
        ip = ipaddress.ip_address(host)
        host_part = f"[{host}]" if ip.version == 6 else host
    except ValueError:
        host_part = host
    if explicit_port is not None:
        host_part = f"{host_part}:{resolved_port}"
    path = parsed.path or "/"
    return urlunsplit((parsed.scheme.lower(), host_part, path, parsed.query, ""))


def _ensure_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> None:
    if (
        ip.is_loopback
        or ip.is_private
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_unspecified
        or ip.is_reserved
        or not ip.is_global
    ):
        raise UnsafeUrlError("Scraper URL host resolves to a non-public address.")


def _headers_to_plain_dict(headers: Any) -> dict[str, str]:
    try:
        items = headers.items()
    except AttributeError:
        items = dict(headers or {}).items()
    return {str(k).lower(): str(v) for k, v in items}


def _charset_from_headers(headers: Mapping[str, str]) -> str | None:
    content_type = headers.get("content-type") or headers.get("Content-Type") or ""
    match = _CHARSET_RE.search(content_type)
    return match.group(1) if match else None
