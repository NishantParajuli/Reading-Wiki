import re
import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator
from urllib.parse import urljoin
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
    if not href or href == "#":
        return ""
    return urljoin(current_url, href)


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

    match = re.search(r"\b(\d+(?:\.\d+)?)\b", title_clean)
    if match:
        return float(match.group(1))

    return None


def _predict_next_url(current_url: str, chapter_num: float | None) -> str:
    """Predicts the next chapter URL by incrementing a trailing numeric path segment
    (e.g. .../series/<slug>/1 -> .../series/<slug>/2). Returns "" if not applicable."""
    parts = current_url.rstrip("/").split("/")
    last_part = parts[-1]
    if re.match(r"^\d+(?:\.\d+)?$", last_part) and chapter_num is not None:
        try:
            next_num = int(chapter_num) + 1
            return "/".join(parts[:-1]) + f"/{next_num}"
        except Exception:
            return ""
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

    async def fetch_text(self, url: str, headers: dict | None = None, encoding: str | None = None) -> str | None:
        try:
            return await safe_fetch_text(self.session, url, encoding=encoding, **self._fetch_kwargs(headers))
        except SafeFetchError as e:
            logger.error("Scraper fetch rejected for %s: %s", describe_url(url), e)
            return None
        except Exception as e:
            logger.error("HTTP request error fetching %s: %s", describe_url(url), e)
            return None

    async def fetch_json(self, url: str, headers: dict | None = None) -> dict | list | None:
        try:
            return await safe_fetch_json(self.session, url, **self._fetch_kwargs(headers))
        except (SafeFetchError, ValueError) as e:
            logger.error("Scraper JSON fetch rejected for %s: %s", describe_url(url), e)
            return None
        except Exception as e:
            logger.error("HTTP request error fetching JSON from %s: %s", describe_url(url), e)
            return None

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

    async def crawl(self, ctx: ScrapeContext) -> AsyncIterator[ChapterData]:
        raise NotImplementedError()
        yield  # pragma: no cover (makes this an async generator)


# ── HTML page-per-chapter adapters ────────────────────────────────────────

class _PagedHtmlAdapter(BaseAdapter):
    """Shared crawl loop for sites that serve one chapter per page and link 'next'.
    Subclasses supply the per-page extraction (title/content/next). Empty content is
    treated as the premium/end boundary; a missing 'next' link falls back to URL
    prediction so sites without explicit nav still advance."""

    def _extract_title(self, parser: HTMLParser, ctx: ScrapeContext) -> str:
        raise NotImplementedError()

    def _extract_content(self, parser: HTMLParser, ctx: ScrapeContext) -> str:
        raise NotImplementedError()

    def _extract_next_url(self, parser: HTMLParser, current_url: str, ctx: ScrapeContext) -> str:
        raise NotImplementedError()

    def _looks_premium(self, parser: HTMLParser) -> bool:
        body = parser.css_first("body")
        text = (body.text(strip=True).lower() if body else "")[:2000]
        return any(marker in text for marker in _PREMIUM_MARKERS)

    async def crawl(self, ctx: ScrapeContext) -> AsyncIterator[ChapterData]:
        current_url = ctx.start_url
        count = 0
        while current_url:
            if ctx.max_chapters is not None and count >= ctx.max_chapters:
                return

            html = await ctx.fetch_text(current_url)
            if html is None:
                return

            parser = HTMLParser(html)
            title = self._extract_title(parser, ctx)
            content = self._extract_content(parser, ctx)
            number = parse_chapter_number(current_url, title)
            next_url = self._extract_next_url(parser, current_url, ctx)

            if not content or len(content) < 50:
                # No real text: either a locked/premium chapter (stop) or a transient
                # blank page. We scrape sequentially from ch.1, so the first empty
                # chapter is the free-tier boundary.
                if ctx.stop_on_premium:
                    logger.info(f"Empty/locked chapter at {current_url}; treating as premium boundary and stopping.")
                    raise PremiumReached(number=number, title=title)
                next_url = next_url or _predict_next_url(current_url, number)
                if not next_url:
                    return
                current_url = next_url
                continue

            yield ChapterData(number=number, title=title, content=content, url=current_url, raw_html=html)
            count += 1

            if not next_url:
                next_url = _predict_next_url(current_url, number)
            if not next_url:
                logger.info("No next chapter URL found and could not predict next. Crawl complete.")
                return
            current_url = next_url


class ReadhiveAdapter(_PagedHtmlAdapter):
    """Concrete adapter for readhive.org."""
    name = "readhive"
    label = "Readhive (readhive.org)"
    requires = ["start_url"]
    default_language = "en"

    def _extract_title(self, parser: HTMLParser, ctx: ScrapeContext) -> str:
        node = parser.css_first("h1")
        if node:
            strong = node.css_first("strong")
            span = node.css_first("span")
            if strong and span:
                return f"{span.text(strip=True)} - {strong.text(strip=True)}"
            elif strong:
                return strong.text(strip=True)
            return node.text(strip=True)
        return "Untitled Chapter"

    def _extract_content(self, parser: HTMLParser, ctx: ScrapeContext) -> str:
        node = parser.css_first("div.prose")
        if not node:
            return ""

        for tag in ("script", "style", "nav", ".ads", ".comments", ".navigation"):
            for el in node.css(tag):
                el.decompose()

        paragraphs = []
        p_nodes = node.css("p")
        if p_nodes:
            for p in p_nodes:
                text = p.text(strip=True)
                if text:
                    paragraphs.append(text)
        if not paragraphs:
            raw_text = node.text(separator="\n", strip=True)
            paragraphs = [p.strip() for p in raw_text.split("\n") if p.strip()]
        return "\n\n".join(paragraphs)

    def _extract_next_url(self, parser: HTMLParser, current_url: str, ctx: ScrapeContext) -> str:
        for node in parser.css("a"):
            text = node.text(strip=True).lower()
            href = node.attributes.get("href", "")
            if not href or href == "#":
                continue
            if text == "next":
                return _absolutize(href, current_url)
        return ""



class FenriRealmAdapter(_PagedHtmlAdapter):
    """Concrete adapter for fenrirealm.com."""
    name = "fenrirealm"
    label = "FenriRealm (fenrirealm.com)"
    requires = ["start_url"]
    default_language = "en"

    def _extract_title(self, parser: HTMLParser, ctx: ScrapeContext) -> str:
        selectors = ["h1.line-clamp-1", "h1.font-outfit", ".chapter-title", "h2", "h1"]
        for sel in selectors:
            node = parser.css_first(sel)
            if node:
                text = node.text(strip=True)
                if text:
                    return text
        return "Untitled Chapter"

    def _extract_content(self, parser: HTMLParser, ctx: ScrapeContext) -> str:
        content_selectors = [
            "div.content-area",
            "div.chapter-view",
            "#reader-area",
            ".entry-content",
            "article",
            "div.reader-content",
        ]
        remove_selectors = [
            "div.my-2",
            "div.hidden.text-center.text-zinc-500",
            "div.my-10.border-t-4.border-dashed.pt-5",
            "script",
            "style",
            "nav",
            ".ads",
            ".comments",
            ".navigation",
            "div.flex.justify-between.my-5",  # common pagination containers
        ]

        for sel in remove_selectors:
            for node in parser.css(sel):
                node.decompose()

        for sel in content_selectors:
            node = parser.css_first(sel)
            if node:
                paragraphs = []
                p_nodes = node.css("p")
                if p_nodes:
                    for p in p_nodes:
                        text = p.text(strip=True)
                        if text:
                            paragraphs.append(text)
                if not paragraphs:
                    raw_text = node.text(separator="\n", strip=True)
                    paragraphs = [p.strip() for p in raw_text.split("\n") if p.strip()]
                content = "\n\n".join(paragraphs)
                if len(content) > 100:  # sanity check for length
                    return content
        return ""

    def _extract_next_url(self, parser: HTMLParser, current_url: str, ctx: ScrapeContext) -> str:
        for node in parser.css("a"):
            rel = node.attributes.get("rel", "") or ""
            href = node.attributes.get("href", "") or ""
            text = node.text(strip=True).lower()
            if not href or href == "#":
                continue
            if "next" in rel.lower() or "next" in text or "next" in (node.attributes.get("class", "") or "").lower():
                return _absolutize(href, current_url)
        return ""





class BotiTranslationAdapter(BaseAdapter):
    """Concrete adapter for botitranslation.com which fetches chapters dynamically via API."""
    name = "boti-translations"
    label = "Boti Translation (botitranslation.com)"
    requires = ["start_url"]
    default_language = "en"
    allowed_hosts = ["api.mystorywave.com"]

    async def crawl(self, ctx: ScrapeContext) -> AsyncIterator[ChapterData]:
        current_url = ctx.start_url
        count = 0
        while current_url:
            if ctx.max_chapters is not None and count >= ctx.max_chapters:
                return

            match = re.search(r"/chapter/(\d+)", current_url)
            if not match:
                logger.error(f"BotiTranslation: Could not parse chapter ID from URL: {current_url}")
                return

            chapter_id = match.group(1)
            api_url = f"https://api.mystorywave.com/story-wave-backend/api/v1/content/chapters/{chapter_id}"

            headers = {
                "site-domain": "www.botitranslation.com",
                "lang": "en_US",
            }

            resp_json = await ctx.fetch_json(api_url, headers=headers)
            if not isinstance(resp_json, dict):
                logger.error(f"BotiTranslation: API response was not an object for chapter {chapter_id}")
                return
            ch_data = resp_json.get("data")
            if not ch_data:
                logger.error(f"BotiTranslation: No data field in API response for chapter {chapter_id}")
                return

            title = ch_data.get("title") or "Untitled Chapter"
            number = parse_chapter_number(current_url, title)

            tier = ch_data.get("tier", 0)
            paywall_status = ch_data.get("paywallStatus", "free")

            if paywall_status != "free" or tier > 0:
                if ctx.stop_on_premium:
                    logger.info(f"BotiTranslation: Premium/locked chapter reached at {current_url} (tier={tier}, paywallStatus={paywall_status}). Stopping.")
                    raise PremiumReached(number=number, title=title)
                else:
                    logger.info(f"BotiTranslation: Premium chapter reached at {current_url} but stop_on_premium is False. Continuing.")

            content_html = ch_data.get("content") or ""
            parser = HTMLParser(content_html)
            paragraphs = [p.text(strip=True) for p in parser.css("p") if p.text(strip=True)]
            if not paragraphs:
                paragraphs = [p.strip() for p in parser.text(separator="\n", strip=True).split("\n") if p.strip()]
            content = "\n\n".join(paragraphs)

            yield ChapterData(
                number=number,
                title=title,
                content=content,
                url=current_url,
                raw_html=json.dumps(resp_json, ensure_ascii=False),
            )
            count += 1

            next_id = ch_data.get("nextId")
            if not next_id:
                logger.info("BotiTranslation: No nextId in API response. Crawl complete.")
                return

            current_url = f"https://www.botitranslation.com/chapter/{next_id}"


class SixtyNineShubaAdapter(_PagedHtmlAdapter):
    """Concrete adapter for 69shuba.com."""
    name = "69shuba"
    label = "69书吧 (69shuba.com)"
    requires = ["start_url"]
    default_language = "zh"

    async def crawl(self, ctx: ScrapeContext) -> AsyncIterator[ChapterData]:
        original_fetch = ctx.fetch_text

        async def wrapped_fetch(url: str) -> str | None:
            http_url = url.replace("https://", "http://")
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "http://www.69shuba.com/",
            }
            retries = 3
            backoff = 5.0
            for attempt in range(retries):
                try:
                    body = await ctx.fetch_bytes(http_url, headers=headers, raise_errors=True)
                    if body is None:
                        return None
                    return body.decode("gbk", errors="ignore")
                except FetchHTTPError as e:
                    if e.status_code == 429 and attempt < retries - 1:
                        logger.warning(f"69shuba: Rate limited (429) fetching {describe_url(http_url)}. Retrying in {backoff}s... (attempt {attempt+1}/{retries})")
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue
                    if attempt < retries - 1:
                        logger.warning(f"69shuba: HTTP {e.status_code} fetching {describe_url(http_url)}. Retrying in {backoff}s... (attempt {attempt+1}/{retries})")
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue
                    logger.error(f"69shuba: HTTP request error fetching {describe_url(http_url)} after {retries} attempts: {e}")
                    return None
                except SafeFetchError as e:
                    logger.error(f"69shuba: Rejected unsafe fetch for {describe_url(http_url)}: {e}")
                    return None
                except Exception as e:
                    if attempt < retries - 1:
                        logger.warning(f"69shuba: Error fetching {describe_url(http_url)}: {e}. Retrying in {backoff}s... (attempt {attempt+1}/{retries})")
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue
                    logger.error(f"69shuba: HTTP request error fetching {describe_url(http_url)} after {retries} attempts: {e}")
                    return None
            return None

        ctx.fetch_text = wrapped_fetch
        try:
            async for ch in super().crawl(ctx):
                if ch.url:
                    ch.url = ch.url.replace("https://", "http://")
                yield ch
        finally:
            ctx.fetch_text = original_fetch

    def _extract_title(self, parser: HTMLParser, ctx: ScrapeContext) -> str:
        node = parser.css_first("h1")
        if node:
            return node.text(strip=True)
        return "Untitled Chapter"

    def _extract_content(self, parser: HTMLParser, ctx: ScrapeContext) -> str:
        node = parser.css_first(".txtnav")
        if not node:
            return ""

        for tag in ["script", "style", "h1", "div.page1"]:
            for el in node.css(tag):
                el.decompose()

        raw_text = node.text(separator="\n", strip=True)
        lines = [line.strip() for line in raw_text.split("\n") if line.strip()]

        cleaned_lines = []
        for line in lines:
            if re.match(r"^\d{4}-\d{2}-\d{2}$", line):
                continue
            if line.startswith("作者：") or "作者:" in line:
                continue
            if "(本章完)" in line or "（本章完）" in line:
                continue
            if "loadAdv(" in line:
                continue
            cleaned_lines.append(line)

        # Skip repeating chapter title at the beginning of the text
        if cleaned_lines:
            first_line = cleaned_lines[0]
            if len(first_line) < 30 and ("第" in first_line and "章" in first_line):
                cleaned_lines.pop(0)

        return "\n\n".join(cleaned_lines)

    def _extract_next_url(self, parser: HTMLParser, current_url: str, ctx: ScrapeContext) -> str:
        for a in parser.css(".txtnav a, .page1 a, a"):
            href = a.attributes.get("href", "")
            text = a.text(strip=True)
            if href and any(x in text for x in ["下一", "next", "下一页", "下一章"]):
                return _absolutize(href, current_url).replace("https://", "http://")
        return ""


class WeTriedTLSAdapter(BaseAdapter):
    """Concrete adapter for wetriedtls.com which parses Next.js RSC next_f payload."""
    name = "wetriedtls"
    label = "WeTried TLS (wetriedtls.com)"
    requires = ["start_url"]
    default_language = "en"

    def _decode_js_string(self, s: str) -> str:
        import json
        import codecs
        try:
            return json.loads(f'"{s}"')
        except Exception:
            try:
                return codecs.escape_decode(bytes(s, "utf-8"))[0].decode("utf-8")
            except Exception:
                return s

    async def crawl(self, ctx: ScrapeContext) -> AsyncIterator[ChapterData]:
        current_url = ctx.start_url
        count = 0
        while current_url:
            if ctx.max_chapters is not None and count >= ctx.max_chapters:
                return

            html = await ctx.fetch_text(current_url)
            if html is None:
                return

            parser = HTMLParser(html)
            buffer_parts = []
            for node in parser.css("script"):
                js_text = node.text()
                if "self.__next_f.push" in js_text:
                    start = 0
                    while True:
                        idx = js_text.find("self.__next_f.push(", start)
                        if idx == -1:
                            break
                        pos = idx + len("self.__next_f.push(")
                        while pos < len(js_text) and js_text[pos] not in ('[', '('):
                            pos += 1
                        if pos >= len(js_text):
                            break
                        pos += 1  # skip '['
                        while pos < len(js_text) and js_text[pos].isdigit():
                            pos += 1
                        while pos < len(js_text) and js_text[pos] in (',', ' ', '\t', '\n', '\r'):
                            pos += 1
                        if pos >= len(js_text) or js_text[pos] != '"':
                            start = pos
                            continue
                        pos += 1  # skip '"'
                        string_chars = []
                        while pos < len(js_text):
                            c = js_text[pos]
                            if c == '"':
                                bs_count = 0
                                temp = pos - 1
                                while temp >= 0 and js_text[temp] == '\\':
                                    bs_count += 1
                                    temp -= 1
                                if bs_count % 2 == 0:
                                    break
                                else:
                                    string_chars.append(c)
                            else:
                                string_chars.append(c)
                            pos += 1
                        raw_str = "".join(string_chars)
                        decoded = self._decode_js_string(raw_str)
                        buffer_parts.append(decoded)
                        start = pos + 1

            full_buffer = "".join(buffer_parts)

            # Extract title
            title_match = re.search(r'"chapter_title"\s*:\s*"([^"]+)"', full_buffer)
            chapter_name_match = re.search(r'"chapter_name"\s*:\s*"([^"]+)"', full_buffer)
            title = "Untitled Chapter"
            if chapter_name_match and title_match:
                title = f"{chapter_name_match.group(1)} - {title_match.group(1)}"
            elif title_match:
                title = title_match.group(1)

            number = parse_chapter_number(current_url, title)

            # Check if locked/premium
            price_match = re.search(r'"price"\s*:\s*(\d+)', full_buffer)
            public_match = re.search(r'"public"\s*:\s*(true|false)', full_buffer)

            is_premium = False
            if price_match and int(price_match.group(1)) > 0:
                is_premium = True
            if public_match and public_match.group(1) == "false":
                is_premium = True

            if is_premium:
                if ctx.stop_on_premium:
                    logger.info(f"Premium/locked chapter reached at {current_url}. Stopping.")
                    raise PremiumReached(number=number, title=title)

            # Extract content reference
            content_ref_match = re.search(r'"chapter_content"\s*:\s*"\$([^"]+)"', full_buffer)
            if not content_ref_match:
                logger.warning(f"Could not find chapter_content reference at {current_url}")
                return

            ref_id = content_ref_match.group(1)
            decl_pattern = re.compile(re.escape(ref_id) + r':T([0-9a-fA-Z]+),')
            decl_match = decl_pattern.search(full_buffer)
            if not decl_match:
                logger.warning(f"Could not find declaration for reference {ref_id} at {current_url}")
                return

            length_hex = decl_match.group(1)
            length = int(length_hex, 16)
            content_start = decl_match.end()
            content_end = content_start + length
            raw_content = full_buffer[content_start:content_end]

            decoded_content = self._decode_js_string(raw_content)

            # Parse HTML to paragraphs
            content_parser = HTMLParser(decoded_content)
            paragraphs = []
            p_nodes = content_parser.css("p")
            for p in p_nodes:
                text = p.text(strip=True)
                if text:
                    paragraphs.append(text)
            if not paragraphs:
                paragraphs = [line.strip() for line in content_parser.text(separator="\n", strip=True).split("\n") if line.strip()]

            content = "\n\n".join(paragraphs)

            yield ChapterData(number=number, title=title, content=content, url=current_url, raw_html=html)
            count += 1

            # Extract next url slug
            next_slug_match = re.search(r'"next_chapter"\s*:\s*\{[^}]+?"chapter_slug"\s*:\s*"([^"]+)"', full_buffer)
            if not next_slug_match:
                logger.info("No next chapter slug found in API response. Crawl complete.")
                return

            next_slug = next_slug_match.group(1)

            # Construct next URL
            base_url = current_url.rstrip("/")
            parts = base_url.split("/")
            if len(parts) > 1:
                current_url = "/".join(parts[:-1]) + "/" + next_slug
            else:
                logger.error(f"Cannot construct next URL from current URL: {current_url} and slug: {next_slug}")
                return


class Novel543Adapter(_PagedHtmlAdapter):
    """Concrete adapter for novel543.com."""
    name = "novel543"
    label = "Novel543 (novel543.com)"
    requires = ["start_url"]
    default_language = "zh"

    def _extract_title(self, parser: HTMLParser, ctx: ScrapeContext) -> str:
        node = parser.css_first(".chapter-content h1") or parser.css_first("h1")
        if node:
            return node.text(strip=True)
        return "Untitled Chapter"

    def _extract_content(self, parser: HTMLParser, ctx: ScrapeContext) -> str:
        node = parser.css_first(".chapter-content .content") or parser.css_first("div.content")
        if not node:
            return ""

        for tag in ("script", "style", "iframe", "ins", ".adBlock", ".gadBlock", ".clickforceads", "#teadunit"):
            for el in node.css(tag):
                el.decompose()

        raw_text = node.text(separator="\n", strip=True)
        paragraphs = []
        for line in raw_text.split("\n"):
            line_stripped = line.strip()
            if not line_stripped:
                continue
            # Filter out promotional/ad lines
            if any(x in line_stripped for x in ("温馨提示", "溫馨提示", "站內信", "免廣告", "切換簡繁體", "VIP會員", "免广告")):
                continue
            paragraphs.append(line_stripped)
            
        return "\n\n".join(paragraphs)

    def _extract_next_url(self, parser: HTMLParser, current_url: str, ctx: ScrapeContext) -> str:
        for node in parser.css(".foot-nav a, a"):
            text = node.text(strip=True)
            href = node.attributes.get("href", "")
            if not href or href == "#":
                continue
            if "下一章" in text:
                return _absolutize(href, current_url)
        return ""

    async def crawl(self, ctx: ScrapeContext) -> AsyncIterator[ChapterData]:
        current_url = ctx.start_url
        count = 0
        pending_chapter = None
        last_number = None

        while current_url:
            if ctx.max_chapters is not None and count >= ctx.max_chapters:
                if pending_chapter:
                    yield pending_chapter
                return

            html = await ctx.fetch_text(current_url)
            if html is None:
                if pending_chapter:
                    yield pending_chapter
                return

            parser = HTMLParser(html)
            title = self._extract_title(parser, ctx)
            content = self._extract_content(parser, ctx)
            parsed_num = parse_chapter_number(current_url, title)
            next_url = self._extract_next_url(parser, current_url, ctx)

            # Strip part info from title like (1/2) or (2/2)
            title_clean = re.sub(r"\s*[(（]\d+/\d+[)）]\s*$", "", title)

            if not content or len(content) < 50:
                if ctx.stop_on_premium:
                    if pending_chapter:
                        yield pending_chapter
                    logger.info(f"Empty/locked chapter at {current_url}; treating as premium boundary and stopping.")
                    raise PremiumReached(number=parsed_num, title=title)
                next_url = next_url or _predict_next_url(current_url, parsed_num)
                if not next_url:
                    if pending_chapter:
                        yield pending_chapter
                    return
                current_url = next_url
                continue

            # Determine the chapter number
            if last_number is None:
                number = parsed_num if parsed_num is not None else 1.0
            else:
                if parsed_num is not None and parsed_num > last_number:
                    number = parsed_num
                else:
                    has_digits = any(c.isdigit() for c in title)
                    is_extra = (not has_digits) or any(x in title for x in (
                        "番外", "外传", "外傳", "特別", "插画", "插畫", "立绘", "立繪", 
                        "感言", "通知", "請假", "请假", "懸賞", "悬赏"
                    ))
                    if is_extra:
                        number = round(last_number + 0.01, 2)
                    else:
                        number = float(int(last_number) + 1)

            is_continuation = False
            if pending_chapter is not None:
                if pending_chapter.number == number and number is not None:
                    is_continuation = True
                elif re.search(r"_\d+_[2-9]\.html$", current_url):
                    is_continuation = True

            if is_continuation and pending_chapter is not None:
                pending_chapter.content += "\n\n" + content
            else:
                if pending_chapter is not None:
                    yield pending_chapter
                    count += 1
                    if ctx.max_chapters is not None and count >= ctx.max_chapters:
                        return
                pending_chapter = ChapterData(number=number, title=title_clean, content=content, url=current_url, raw_html=html)
                last_number = number

            if not next_url:
                next_url = _predict_next_url(current_url, number)
            if not next_url:
                logger.info("No next chapter URL found and could not predict next. Crawl complete.")
                if pending_chapter:
                    yield pending_chapter
                return
            current_url = next_url

        if pending_chapter:
            yield pending_chapter


# ── Adapter registry ──────────────────────────────────────────────────────
ADAPTERS: dict[str, type[BaseAdapter]] = {
    "fenrirealm": FenriRealmAdapter,
    "readhive": ReadhiveAdapter,
    "boti-translations": BotiTranslationAdapter,
    "69shuba": SixtyNineShubaAdapter,
    "wetriedtls": WeTriedTLSAdapter,
    "novel543": Novel543Adapter,
}


def get_adapter(name: str | None = None) -> BaseAdapter:
    """Returns the configured site adapter (defaults to settings.SCRAPER_ADAPTER)."""
    key = (name or settings.SCRAPER_ADAPTER or "fenrirealm").lower()
    cls = ADAPTERS.get(key)
    if cls is None:
        logger.warning(f"Unknown adapter '{key}', falling back to 'fenrirealm'.")
        cls = FenriRealmAdapter
    return cls()


def list_adapters() -> list[dict]:
    """Metadata for the Add-Source dropdown in the UI."""
    out = []
    for key, cls in ADAPTERS.items():
        out.append({
            "name": key,
            "label": getattr(cls, "label", key),
            "requires": list(getattr(cls, "requires", ["start_url"])),
            "default_language": getattr(cls, "default_language", "en"),
        })
    return out
