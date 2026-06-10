import re
import asyncio
import logging
from dataclasses import dataclass, field
from typing import AsyncIterator
import lxml.html
from curl_cffi.requests import AsyncSession
from selectolax.parser import HTMLParser
from novelwiki.config.settings import settings

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
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        match = re.match(r"(https?://[^/]+)", current_url)
        domain = match.group(1) if match else settings.SCRAPER_BASE_URL.rstrip("/")
        return f"{domain}{href}"
    return href


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

    async def fetch_text(self, url: str) -> str | None:
        try:
            resp = await self.session.get(url, impersonate="chrome", timeout=30.0)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.error(f"HTTP request error fetching {url}: {e}")
            return None


class BaseAdapter:
    """Base interface for all site/format adapters. An adapter OWNS its crawl: given a
    ScrapeContext it yields normalized ChapterData in reading order, raising PremiumReached
    when it can go no further on the free tier."""
    name: str = "base"
    label: str = "Base"
    requires: list[str] = ["start_url"]   # what the Add-Source form must collect
    default_language: str = "en"

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


class GenericAdapter(_PagedHtmlAdapter):
    """Config-driven adapter: reads CSS selectors from the source config (falling back
    to settings) so a new HTML site can be supported without writing code."""
    name = "generic"
    label = "Generic (CSS selectors)"
    requires = ["start_url"]
    default_language = "en"

    def _sel(self, ctx: ScrapeContext, key: str, default: str) -> str:
        return (ctx.config or {}).get(key) or default

    def _extract_title(self, parser: HTMLParser, ctx: ScrapeContext) -> str:
        node = parser.css_first(self._sel(ctx, "title_selector", settings.SCRAPER_TITLE_SELECTOR))
        return node.text(strip=True) if node else "Untitled Chapter"

    def _extract_content(self, parser: HTMLParser, ctx: ScrapeContext) -> str:
        for sel in ("script", "style", "nav", ".ads", ".comments", ".navigation"):
            for node in parser.css(sel):
                node.decompose()
        node = parser.css_first(self._sel(ctx, "content_selector", settings.SCRAPER_CONTENT_SELECTOR))
        if not node:
            return ""
        paragraphs = [p.text(strip=True) for p in node.css("p") if p.text(strip=True)]
        if not paragraphs:
            raw = node.text(separator="\n", strip=True)
            paragraphs = [p.strip() for p in raw.split("\n") if p.strip()]
        return "\n\n".join(paragraphs)

    def _extract_next_url(self, parser: HTMLParser, current_url: str, ctx: ScrapeContext) -> str:
        node = parser.css_first(self._sel(ctx, "next_selector", settings.SCRAPER_NEXT_SELECTOR))
        if node:
            return _absolutize(node.attributes.get("href", ""), current_url)
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


class GenericXPathAdapter(_PagedHtmlAdapter):
    """Config-driven adapter using XPath: reads XPath selectors from the source config
    so a new HTML site can be supported without writing code."""
    name = "generic_xpath"
    label = "Generic (XPath selectors)"
    requires = ["start_url"]
    default_language = "en"

    def _sel(self, ctx: ScrapeContext, key: str, default: str) -> str:
        return (ctx.config or {}).get(key) or default

    async def crawl(self, ctx: ScrapeContext) -> AsyncIterator[ChapterData]:
        original_fetch = ctx.fetch_text

        async def wrapped_fetch(url: str) -> str | None:
            html_str = await original_fetch(url)
            self._current_html = html_str
            return html_str

        ctx.fetch_text = wrapped_fetch
        try:
            async for ch in super().crawl(ctx):
                yield ch
        finally:
            ctx.fetch_text = original_fetch

    def _get_tree(self) -> lxml.html.HtmlElement | None:
        html_str = getattr(self, "_current_html", None)
        if not html_str:
            return None
        return lxml.html.fromstring(html_str)

    def _extract_title(self, parser: HTMLParser, ctx: ScrapeContext) -> str:
        tree = self._get_tree()
        if tree is None:
            return "Untitled Chapter"
        xpath_expr = self._sel(ctx, "title_xpath", "//h1")
        nodes = tree.xpath(xpath_expr)
        if nodes:
            node = nodes[0]
            if isinstance(node, str):
                return node.strip()
            return node.text_content().strip() if hasattr(node, "text_content") else str(node).strip()
        return "Untitled Chapter"

    def _extract_content(self, parser: HTMLParser, ctx: ScrapeContext) -> str:
        tree = self._get_tree()
        if tree is None:
            return ""
        # Strip script, style, nav, ads, comments, navigation
        for bad_tag in ("script", "style", "nav", ".ads", ".comments", ".navigation"):
            if bad_tag.startswith("."):
                class_name = bad_tag[1:]
                for el in tree.xpath(f"//*[contains(@class, '{class_name}')]"):
                    el.getparent().remove(el)
            else:
                for el in tree.xpath(f"//{bad_tag}"):
                    el.getparent().remove(el)

        xpath_expr = self._sel(ctx, "content_xpath", "//article")
        nodes = tree.xpath(xpath_expr)
        if not nodes:
            return ""

        node = nodes[0]
        paragraphs = []
        if hasattr(node, "xpath"):
            p_nodes = node.xpath(".//p")
            if p_nodes:
                for p in p_nodes:
                    txt = p.text_content().strip()
                    if txt:
                        paragraphs.append(txt)
        if not paragraphs:
            raw_text = node.text_content() if hasattr(node, "text_content") else str(node)
            paragraphs = [p.strip() for p in raw_text.split("\n") if p.strip()]

        return "\n\n".join(paragraphs)

    def _extract_next_url(self, parser: HTMLParser, current_url: str, ctx: ScrapeContext) -> str:
        tree = self._get_tree()
        if tree is None:
            return ""
        xpath_expr = self._sel(ctx, "next_xpath", "//a[@rel='next']")
        nodes = tree.xpath(xpath_expr)
        if nodes:
            node = nodes[0]
            href = ""
            if isinstance(node, str):
                href = node
            elif hasattr(node, "get"):
                href = node.get("href") or ""
            elif hasattr(node, "attrib"):
                href = node.attrib.get("href") or ""
            return _absolutize(href, current_url)
        return ""


class BotiTranslationAdapter(BaseAdapter):
    """Concrete adapter for botitranslation.com which fetches chapters dynamically via API."""
    name = "boti-translations"
    label = "Boti Translation (botitranslation.com)"
    requires = ["start_url"]
    default_language = "en"

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

            try:
                resp = await ctx.session.get(api_url, headers=headers, impersonate="chrome", timeout=30.0)
                if resp.status_code != 200:
                    logger.error(f"BotiTranslation: API request failed with status {resp.status_code} for chapter {chapter_id}")
                    return

                resp_json = resp.json()
                ch_data = resp_json.get("data")
                if not ch_data:
                    logger.error(f"BotiTranslation: No data field in API response for chapter {chapter_id}")
                    return
            except Exception as e:
                logger.error(f"BotiTranslation: HTTP or JSON error fetching chapter {chapter_id}: {e}")
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
                raw_html=resp.text,
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
                    resp = await ctx.session.get(http_url, headers=headers, impersonate="chrome", timeout=30.0)
                    if resp.status_code == 429:
                        logger.warning(f"69shuba: Rate limited (429) fetching {http_url}. Retrying in {backoff}s... (attempt {attempt+1}/{retries})")
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue
                    resp.raise_for_status()
                    return resp.content.decode("gbk", errors="ignore")
                except Exception as e:
                    if attempt < retries - 1:
                        logger.warning(f"69shuba: Error fetching {http_url}: {e}. Retrying in {backoff}s... (attempt {attempt+1}/{retries})")
                        await asyncio.sleep(backoff)
                        backoff *= 2
                        continue
                    logger.error(f"69shuba: HTTP request error fetching {http_url} after {retries} attempts: {e}")
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


# ── Adapter registry ──────────────────────────────────────────────────────
ADAPTERS: dict[str, type[BaseAdapter]] = {
    "fenrirealm": FenriRealmAdapter,
    "generic": GenericAdapter,
    "generic_xpath": GenericXPathAdapter,
    "boti-translations": BotiTranslationAdapter,
    "69shuba": SixtyNineShubaAdapter,
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
