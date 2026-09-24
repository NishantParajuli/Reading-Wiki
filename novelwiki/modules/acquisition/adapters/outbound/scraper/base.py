import re
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit
import lxml.html
from curl_cffi.requests import AsyncSession
from selectolax.parser import HTMLParser
from novelwiki.platform.config import settings
from novelwiki.modules.acquisition.adapters.outbound.scraper.safe_fetch import (
    FetchHTTPError,
    SafeFetchError,
    describe_url,
    safe_fetch_bytes,
    safe_fetch_json,
    safe_fetch_text,
)

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Words that, when they dominate an otherwise empty chapter body, indicate a
# locked/premium chapter rather than a transient failure.
_PREMIUM_MARKERS = ("premium", "unlock", "locked", "coins", "subscribe", "members only", "advance chapter")


def _absolutize(href: str, current_url: str) -> str:
    if not href or href.startswith("#"):
        return ""
    absolute = urljoin(current_url, href)
    return absolute if urlsplit(absolute).scheme in {"http", "https"} else ""


def _chapter_text(node) -> str:
    """Keep inline words together and preserve explicit paragraph/line breaks."""
    root = lxml.html.fromstring(node.html)
    for unwanted in root.xpath(".//script|.//style|.//nav|.//button|.//iframe"):
        unwanted.drop_tree()
    for line_break in root.xpath(".//br"):
        line_break.tail = "\n" + (line_break.tail or "")
    paragraphs = root.xpath(".//p|.//li[not(.//p)]|.//blockquote[not(.//p)]")
    parts = [item.text_content().strip() for item in paragraphs] if paragraphs else root.text_content().splitlines()
    return "\n\n".join(part.strip() for part in parts if part.strip())


def _visit_url(url: str, seen: set[str]) -> None:
    key = urldefrag(url)[0].rstrip("/")
    if key in seen:
        raise ScrapeError("Chapter navigation repeated an already visited page.")
    seen.add(key)


def _javascript_object(script: str, property_name: str) -> dict | None:
    """Read a JSON-compatible object literal without executing page JavaScript."""
    marker = re.search(rf"\b{re.escape(property_name)}\s*:\s*\{{", script)
    if not marker:
        return None
    start = marker.end() - 1
    position, depth = start, 0
    decoder = json.JSONDecoder()
    while position < len(script):
        char = script[position]
        if char == '"':
            _, consumed = decoder.raw_decode(script[position:])
            position += consumed
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                literal = script[start:position + 1]
                quoted = re.sub(
                    r'"(?:\\.|[^"\\])*"|([A-Za-z_$][\w$]*)(\s*:)',
                    lambda match: json.dumps(match[1]) + match[2] if match[1] else match[0],
                    literal,
                )
                return json.loads(quoted)
        position += 1
    raise ScrapeError("The source returned an incomplete chapter data object.")


def _rich_text(document) -> str:
    if isinstance(document, list):
        return "".join(_rich_text(item) for item in document)
    if not isinstance(document, dict):
        return ""
    if document.get("type") == "text":
        return str(document.get("text") or "")
    if document.get("type") == "hardBreak":
        return "\n"
    text = _rich_text(document.get("content") or [])
    return text + "\n\n" if document.get("type") in {"paragraph", "heading", "codeBlock"} else text


def parse_chapter_number(url: str, title: str) -> float | None:
    """Parses a chapter number (int or float) from a title or URL. Shared by adapters."""
    title_clean = re.sub(r"\s+", " ", title or "")

    match = re.search(r"(?i)chapter\s+(\d+(?:\.\d+)?)", title_clean)
    if match:
        return float(match.group(1))

    match = re.search(r"(?i)\bch\b\.?\s*(\d+(?:\.\d+)?)", title_clean)
    if match:
        return float(match.group(1))

    match = re.search(r"(?i)chapter-(\d+(?:[.-]\d+)?)", url or "")
    if match:
        raw_num = match.group(1)
        if "-" in raw_num:
            raw_num = raw_num.replace("-", ".")
        try:
            return float(raw_num)
        except ValueError:
            pass

    # Chinese patterns: e.g. 第123章, 第123话, 第123.5章
    match = re.search(r"第\s*(\d+(?:\.\d+)?)\s*[章话集页]", title_clean)
    if match:
        return float(match.group(1))

    match = re.search(r"第\s*([零〇一二两兩三四五六七八九十百千万萬]+)\s*[章话話集]", title_clean)
    if match:
        digits = dict(zip("零〇一二两兩三四五六七八九", [0, 0, 1, 2, 2, 2, 3, 4, 5, 6, 7, 8, 9]))
        units = {"十": 10, "百": 100, "千": 1000, "万": 10000, "萬": 10000}
        total = section = number = 0
        for char in match.group(1):
            if char in digits:
                number = number * 10 + digits[char]
            elif units[char] == 10000:
                total += (section + number) * 10000
                section = number = 0
            else:
                section += (number or 1) * units[char]
                number = 0
        return float(total + section + number)

    match = re.search(r"\b(\d+(?:\.\d+)?)\b", title_clean)
    if match:
        return float(match.group(1))

    return None


def _predict_next_url(current_url: str, chapter_num: float | None) -> str:
    """Predicts the next chapter URL by incrementing a trailing numeric path segment
    (e.g. .../series/<slug>/1 -> .../series/<slug>/2). Returns "" if not applicable."""
    parsed = urlsplit(current_url)
    directory, _, last_part = parsed.path.rstrip("/").rpartition("/")
    match = re.fullmatch(r"(chapter-)?(\d+)", last_part, re.IGNORECASE)
    if match and chapter_num is not None and float(match[2]) == chapter_num:
        next_path = f"{directory}/{match[1] or ''}{int(chapter_num) + 1}"
        return urlunsplit((parsed.scheme, parsed.netloc, next_path, "", ""))
    return ""


# ── Normalized scrape primitives ──────────────────────────────────────────

@dataclass
class ChapterData:
    """One scraped chapter, in the source's own language. `number` is the source-LOCAL
    chapter index; the runner adds the source's chapter_offset to derive the global number."""
    number: float | None
    title: str
    content: str
    url: str | None = None
    raw_html: str | None = None


class PremiumReached(Exception):
    """Raised by an adapter when it reaches a locked/premium chapter it cannot scrape.
    The runner catches it and stops the crawl cleanly (we scrape only what's free)."""
    def __init__(self, number: float | None = None, title: str | None = None):
        self.number = number
        self.title = title
        super().__init__(f"Premium/locked chapter reached (number={number}, title={title!r})")


class ScrapeError(RuntimeError):
    """A source fetch or parse failed; it is not a successful end of the book."""


@dataclass
class ScrapeContext:
    """Everything an adapter needs to run a crawl. The runner builds this and the
    adapter drives navigation, yielding ChapterData until exhausted or premium."""
    start_url: str
    session: AsyncSession
    config: dict = field(default_factory=dict)   # per-source adapter config (e.g. selectors)
    max_chapters: int | None = None
    stop_on_premium: bool = True
    source_host: str | None = None
    allowed_hosts: set[str] = field(default_factory=set)
    require_same_host: bool = True

    def _fetch_kwargs(self, headers: dict | None = None) -> dict:
        return {
            "source_host": self.source_host,
            "allowed_hosts": self.allowed_hosts,
            "require_same_host": self.require_same_host,
            "headers": headers,
        }

    async def fetch_text(self, url: str, headers: dict | None = None, encoding: str | None = None) -> str:
        try:
            return await safe_fetch_text(self.session, url, encoding=encoding, **self._fetch_kwargs(headers))
        except SafeFetchError as e:
            logger.error("Scraper fetch rejected for %s: %s", describe_url(url), e)
            raise
        except Exception as e:
            logger.error("HTTP request error fetching %s: %s", describe_url(url), e)
            raise ScrapeError(f"Could not fetch chapter from {describe_url(url)}.") from e

    async def fetch_json(self, url: str, headers: dict | None = None) -> dict | list:
        try:
            return await safe_fetch_json(self.session, url, **self._fetch_kwargs(headers))
        except (SafeFetchError, ValueError) as e:
            logger.error("Scraper JSON fetch rejected for %s: %s", describe_url(url), e)
            raise
        except Exception as e:
            logger.error("HTTP request error fetching JSON from %s: %s", describe_url(url), e)
            raise ScrapeError(f"Could not fetch chapter data from {describe_url(url)}.") from e

    async def fetch_bytes(self, url: str, headers: dict | None = None, raise_errors: bool = False) -> bytes | None:
        try:
            return await safe_fetch_bytes(self.session, url, **self._fetch_kwargs(headers))
        except SafeFetchError as e:
            if raise_errors:
                raise
            logger.error("Scraper byte fetch rejected for %s: %s", describe_url(url), e)
            return None
        except Exception as e:
            if raise_errors:
                raise
            logger.error("HTTP request error fetching bytes from %s: %s", describe_url(url), e)
            return None


class BaseAdapter:
    """Base interface for all site/format adapters. An adapter OWNS its crawl: given a
    ScrapeContext it yields normalized ChapterData in reading order, raising PremiumReached
    when it can go no further on the free tier."""
    name: str = "base"
    label: str = "Base"
    requires: list[str] = ["start_url"]   # what the Add-Source form must collect
    default_language: str = "en"
    allowed_hosts: list[str] = []
    start_url_hint: str = "Paste the first chapter URL to start reading from."

    async def crawl(self, ctx: ScrapeContext) -> AsyncIterator[ChapterData]:
        raise NotImplementedError()
        yield  # pragma: no cover (makes this an async generator)
