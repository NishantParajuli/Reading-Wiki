"""Site-specific chapter extraction and the scraper adapter registry."""

import asyncio
import json
import logging
import re
from typing import AsyncIterator
from urllib.parse import urljoin, urlsplit

from selectolax.parser import HTMLParser

from novelwiki.platform.config import settings
from novelwiki.modules.acquisition.adapters.outbound.scraper.safe_fetch import FetchHTTPError
from novelwiki.modules.acquisition.adapters.outbound.scraper.base import (
    HEADERS, BaseAdapter, ChapterData, PremiumReached, ScrapeContext, ScrapeError,
    _absolutize, _chapter_text, _javascript_object, _predict_next_url, _rich_text,
    _visit_url, parse_chapter_number,
)
from novelwiki.modules.acquisition.adapters.outbound.scraper.novelpia import FuckNovelpiaAdapter
from novelwiki.modules.acquisition.adapters.outbound.scraper.raw_archive import RawFuckNovelpiaAdapter
from novelwiki.modules.acquisition.adapters.outbound.scraper.translation_sites import (
    AzureChroniclesAdapter, DreamyTranslationsAdapter, PenguinSquadAdapter,
)

logger = logging.getLogger(__name__)


# ── HTML page-per-chapter adapters ────────────────────────────────────────

class _PagedHtmlAdapter(BaseAdapter):
    """Shared crawl loop for sites that serve one chapter per page and link 'next'.
    Subclasses supply the per-page extraction (title/content/next). Empty content is
    rejected unless an explicit paywall is present. Numeric chapter paths can
    predict a next URL when server-rendered navigation is absent."""

    def _extract_title(self, parser: HTMLParser, ctx: ScrapeContext) -> str:
        raise NotImplementedError()

    def _extract_content(self, parser: HTMLParser, ctx: ScrapeContext) -> str:
        raise NotImplementedError()

    def _extract_next_url(self, parser: HTMLParser, current_url: str, ctx: ScrapeContext) -> str:
        raise NotImplementedError()

    async def _fetch_page(self, ctx: ScrapeContext, url: str) -> str:
        return await ctx.fetch_text(url)

    def _looks_premium(self, parser: HTMLParser) -> bool:
        if parser.css_first('.paywall, .chapter-locked, [data-locked="true"]'):
            return True
        body = parser.css_first("body")
        text = (body.text(strip=True).lower() if body else "")[:2000]
        return bool(re.search(r"unlock (?:this |the )?chapter|chapter (?:is )?locked|members only|subscribe to (?:read|continue)", text))

    async def crawl(self, ctx: ScrapeContext) -> AsyncIterator[ChapterData]:
        current_url = ctx.start_url
        count = 0
        seen: set[str] = set()
        predicted = False
        while current_url:
            if ctx.max_chapters is not None and count >= ctx.max_chapters:
                return

            _visit_url(current_url, seen)
            try:
                html = await self._fetch_page(ctx, current_url)
            except FetchHTTPError as exc:
                if predicted and exc.status_code in {404, 410}:
                    return
                raise
            if html is None:
                raise ScrapeError("Chapter fetch returned no response.")

            parser = HTMLParser(html)
            title = self._extract_title(parser, ctx)
            number = parse_chapter_number(current_url, title)
            next_url = self._extract_next_url(parser, current_url, ctx)
            premium = self._looks_premium(parser)
            # Content cleanup may remove navigation; capture it first.
            content = self._extract_content(parser, ctx)

            if premium and (not content.strip() or parser.css_first('.paywall, .chapter-locked, [data-locked="true"]')):
                if ctx.stop_on_premium:
                    raise PremiumReached(number=number, title=title)
                if not next_url:
                    return
                current_url = next_url
                continue
            if not content.strip():
                raise ScrapeError(f"{self.label}: no chapter content found; the source may be blocked or its layout changed.")

            yield ChapterData(number=number, title=title, content=content, url=current_url, raw_html=html)
            count += 1

            predicted = not bool(next_url)
            if predicted:
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
    start_url_hint = "Paste a chapter URL: https://readhive.org/series/<series-id>/<chapter>/"

    def _extract_title(self, parser: HTMLParser, ctx: ScrapeContext) -> str:
        node = parser.css_first("h1")
        if node:
            strong = node.css_first("strong")
            span = node.css_first("span")
            if strong and span:
                return " - ".join(filter(None, [span.text(strip=True), strong.text(strip=True)]))
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

        return _chapter_text(node)

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
    start_url_hint = "Paste a chapter URL: https://fenrirealm.com/series/<series-slug>/1"

    def _chapter_data(self, parser: HTMLParser) -> dict | None:
        for node in parser.css("script"):
            if "chapterData:" in node.text() or "chapterData :" in node.text():
                try:
                    return _javascript_object(node.text(), "chapterData")
                except (TypeError, ValueError) as exc:
                    raise ScrapeError("FenriRealm returned invalid chapter data.") from exc
        return None

    def _looks_premium(self, parser: HTMLParser) -> bool:
        data = self._chapter_data(parser)
        if data is not None:
            return bool(not data.get("content") and (data.get("locked") or {}).get("price"))
        return super()._looks_premium(parser)

    def _extract_title(self, parser: HTMLParser, ctx: ScrapeContext) -> str:
        data = self._chapter_data(parser)
        if data:
            return str(data.get("name") or data.get("title") or "Untitled Chapter")
        selectors = ["h1.line-clamp-1", "h1.font-outfit", ".chapter-title", "h2", "h1"]
        for sel in selectors:
            node = parser.css_first(sel)
            if node:
                text = node.text(strip=True)
                if text:
                    return text
        return "Untitled Chapter"

    def _extract_content(self, parser: HTMLParser, ctx: ScrapeContext) -> str:
        data = self._chapter_data(parser)
        if data is not None:
            content = data.get("content") or ""
            if not content:
                return ""
            if data.get("content_format") == "json":
                try:
                    return _rich_text(json.loads(content) if isinstance(content, str) else content).strip()
                except (TypeError, ValueError) as exc:
                    raise ScrapeError("FenriRealm returned invalid rich chapter text.") from exc
            return _chapter_text(HTMLParser(str(content)).body)
        content_selectors = [
            '[role="region"].reader-area',
            "div.content-area",
            "#reader-area",
            ".entry-content",
            "article",
            "div.reader-content",
            "div.chapter-view",
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

        for sel in content_selectors:
            node = parser.css_first(sel)
            if node:
                isolated = HTMLParser(node.html)
                for remove in remove_selectors:
                    for unwanted in isolated.css(remove):
                        unwanted.decompose()
                content = _chapter_text(isolated.body)
                if content:
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
    start_url_hint = "Paste a chapter URL: https://www.botitranslation.com/chapter/<chapter-id>"

    async def crawl(self, ctx: ScrapeContext) -> AsyncIterator[ChapterData]:
        current_url = ctx.start_url
        count = 0
        seen: set[str] = set()
        while current_url:
            if ctx.max_chapters is not None and count >= ctx.max_chapters:
                return

            _visit_url(current_url, seen)

            match = re.search(r"/chapter/(\d+)", current_url)
            if not match:
                raise ScrapeError("Boti Translation requires a chapter URL containing /chapter/<id>.")

            chapter_id = match.group(1)
            api_url = f"https://api.mystorywave.com/story-wave-backend/api/v1/content/chapters/{chapter_id}"

            headers = {
                "site-domain": "www.botitranslation.com",
                "lang": "en_US",
            }

            resp_json = await ctx.fetch_json(api_url, headers=headers)
            if not isinstance(resp_json, dict):
                raise ScrapeError("Boti Translation returned an invalid chapter response.")
            ch_data = resp_json.get("data")
            if not isinstance(ch_data, dict) or not ch_data:
                raise ScrapeError("Boti Translation returned no chapter data.")

            title = ch_data.get("title") or "Untitled Chapter"
            number = parse_chapter_number(current_url, title)

            tier = float(ch_data.get("tier") or 0)
            paywall_status = str(ch_data.get("paywallStatus") or "free").lower()
            next_id = ch_data.get("nextId")
            if next_id is not None and (isinstance(next_id, bool) or not str(next_id).isdigit()):
                raise ScrapeError("Boti Translation returned an invalid next chapter identifier.")
            next_url = urljoin(current_url, f"/chapter/{next_id}") if next_id and int(next_id) > 0 else ""

            if paywall_status != "free" or tier > 0:
                if ctx.stop_on_premium:
                    logger.info(f"BotiTranslation: Premium/locked chapter reached at {current_url} (tier={tier}, paywallStatus={paywall_status}). Stopping.")
                    raise PremiumReached(number=number, title=title)
                else:
                    current_url = next_url
                    continue

            content_html = ch_data.get("content") or ""
            parser = HTMLParser(content_html)
            content = _chapter_text(parser.body)
            if not content:
                raise ScrapeError("Boti Translation returned an empty free chapter.")

            yield ChapterData(
                number=number,
                title=title,
                content=content,
                url=current_url,
                raw_html=json.dumps(resp_json, ensure_ascii=False),
            )
            count += 1

            if not next_url:
                logger.info("BotiTranslation: No nextId in API response. Crawl complete.")
                return

            current_url = next_url


class SixtyNineShubaAdapter(_PagedHtmlAdapter):
    """Concrete adapter for 69shuba.com."""
    name = "69shuba"
    label = "69书吧 (69shuba.com)"
    requires = ["start_url"]
    default_language = "zh"
    start_url_hint = "Paste a chapter URL: https://www.69shuba.com/txt/<book-id>/<chapter-id>"

    async def _fetch_page(self, ctx: ScrapeContext, url: str) -> str:
        headers = {
            **HEADERS,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": urljoin(url, "/"),
        }
        for attempt in range(3):
            try:
                body = await ctx.fetch_bytes(url, headers=headers, raise_errors=True)
                if body is None:
                    raise ScrapeError("69shuba returned no chapter response.")
                # Older pages are GBK; newer pages can be UTF-8. Never silently
                # discard undecodable source characters or downgrade HTTPS.
                charset = re.search(rb'charset=["\']?([A-Za-z0-9_-]+)', body[:4096], re.I)
                if charset:
                    try:
                        return body.decode(charset[1].decode("ascii"), errors="replace")
                    except LookupError:
                        pass
                try:
                    return body.decode("utf-8")
                except UnicodeDecodeError:
                    return body.decode("gb18030", errors="replace")
            except FetchHTTPError as exc:
                if exc.status_code not in {429, 500, 502, 503, 504} or attempt == 2:
                    raise
                await asyncio.sleep(5.0 * (2 ** attempt))
        raise ScrapeError("69shuba could not fetch the chapter.")

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
            if re.match(r"^\d{4}-\d{2}-\d{2}(?:\s|$)", line):
                continue
            if line.startswith("作者：") or "作者:" in line:
                continue
            line = line.replace("(本章完)", "").replace("（本章完）", "").strip()
            if not line:
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
                return _absolutize(href, current_url)
        return ""


class WeTriedTLSAdapter(BaseAdapter):
    """Read public chapter data from Next.js Flight without running scripts."""
    name = "wetriedtls"
    label = "WeTried TLS (wetriedtls.com)"
    requires = ["start_url"]
    default_language = "en"
    start_url_hint = "Paste a chapter URL: https://wetriedtls.com/series/<series-slug>/chapter-1"

    def _flight_records(self, parser: HTMLParser) -> dict:
        parts = []
        decoder = json.JSONDecoder()
        for node in parser.css("script"):
            script = node.text()
            for marker in re.finditer(r"self\.__next_f\.push\(", script):
                try:
                    value, _ = decoder.raw_decode(script[marker.end():].lstrip())
                except ValueError:
                    continue
                if isinstance(value, list) and len(value) > 1 and value[0] == 1 and isinstance(value[1], str):
                    parts.append(value[1])
        data = "".join(parts).encode("utf-8")
        records = {}
        position = 0
        while position < len(data):
            if data[position:position + 1] == b"\n":
                position += 1
                continue
            marker = re.match(rb"([0-9a-fA-F]+):", data[position:])
            if not marker:
                following = data.find(b"\n", position)
                if following < 0:
                    break
                position = following + 1
                continue
            ref = marker[1].decode("ascii")
            position += marker.end()
            text_record = re.match(rb"T([0-9a-fA-F]+),", data[position:])
            if text_record:
                position += text_record.end()
                end = position + int(text_record[1], 16)
                if end > len(data):
                    raise ScrapeError("WeTried TLS returned incomplete chapter text.")
                records[ref] = data[position:end].decode("utf-8")
                position = end
            else:
                end = data.find(b"\n", position)
                if end < 0:
                    end = len(data)
                try:
                    records[ref] = json.loads(data[position:end])
                except (ValueError, UnicodeDecodeError):
                    pass  # import/debug/stream-control records are not chapter data
                position = end + 1
        return records

    def _chapter_record(self, records: dict) -> tuple[dict, dict]:
        def find(value, parent=None):
            if isinstance(value, dict):
                if "chapter_content" in value:
                    return value, parent if isinstance(parent, dict) else value
                children = value.values()
            elif isinstance(value, list):
                children = value
            else:
                return None
            for child in children:
                found = find(child, value)
                if found:
                    return found
            return None
        for value in records.values():
            found = find(value)
            if found:
                return found
        raise ScrapeError("WeTried TLS returned no chapter data; the source may be blocked or its layout changed.")

    async def crawl(self, ctx: ScrapeContext) -> AsyncIterator[ChapterData]:
        current_url = ctx.start_url
        count = 0
        seen: set[str] = set()
        while current_url:
            if ctx.max_chapters is not None and count >= ctx.max_chapters:
                return
            _visit_url(current_url, seen)
            html = await ctx.fetch_text(current_url)
            if html is None:
                raise ScrapeError("WeTried TLS returned no chapter response.")
            records = self._flight_records(HTMLParser(html))
            chapter, container = self._chapter_record(records)
            title = " - ".join(str(chapter[key]) for key in ("chapter_name", "chapter_title") if chapter.get(key))
            number = parse_chapter_number(current_url, title)
            next_chapter = container.get("next_chapter") or {}
            next_slug = next_chapter.get("chapter_slug") if isinstance(next_chapter, dict) else None
            next_url = _absolutize(str(next_slug), current_url.rstrip("/")) if next_slug else ""
            if chapter.get("public") is False or float(chapter.get("price") or 0) > 0:
                if ctx.stop_on_premium:
                    raise PremiumReached(number=number, title=title)
                current_url = next_url
                continue
            content = chapter.get("chapter_content")
            if isinstance(content, str) and content.startswith("$"):
                content = records.get(content[1:])
            if not isinstance(content, str) or not content:
                raise ScrapeError("WeTried TLS returned no readable chapter text.")
            # Flight T-record lengths count UTF-8 bytes. Their text has already
            # been decoded from JavaScript exactly once; decoding it again would
            # corrupt literal backslashes and quotation marks in the story.
            text = _chapter_text(HTMLParser(content).body)
            if not text:
                raise ScrapeError("WeTried TLS returned an empty free chapter.")
            yield ChapterData(number=number, title=title, content=text, url=current_url, raw_html=html)
            count += 1
            current_url = next_url


class Novel543Adapter(_PagedHtmlAdapter):
    """Concrete adapter for novel543.com."""
    name = "novel543"
    label = "Novel543 (novel543.com)"
    requires = ["start_url"]
    default_language = "zh"
    start_url_hint = "Paste the first page of a chapter: https://www.novel543.com/<book-id>/8096_1.html"

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

    @staticmethod
    def _page_identity(url: str) -> tuple[str, int] | None:
        path = urlsplit(url).path
        match = re.search(r"/([^/_]+)_(\d+)(?:_(\d+))?\.html$", path)
        if not match:
            return None
        return path[:match.start()] + f"/{match[1]}_{match[2]}", int(match[3] or 1)

    def _is_continuation(self, first_url: str, next_url: str) -> bool:
        first, following = self._page_identity(first_url), self._page_identity(next_url)
        return bool(first and following and first[0] == following[0] and following[1] > first[1])

    async def crawl(self, ctx: ScrapeContext) -> AsyncIterator[ChapterData]:
        current_url = ctx.start_url
        count = 0
        pending = None
        last_number = None
        seen: set[str] = set()
        while current_url:
            if ctx.max_chapters is not None and count >= ctx.max_chapters:
                return
            _visit_url(current_url, seen)
            html = await ctx.fetch_text(current_url)
            if html is None:
                raise ScrapeError("Novel543 returned no chapter response.")
            parser = HTMLParser(html)
            title = self._extract_title(parser, ctx)
            title_clean = re.sub(r"\s*[(（]\d+/\d+[)）]\s*$", "", title)
            parsed_number = parse_chapter_number(current_url, title_clean)
            next_url = self._extract_next_url(parser, current_url, ctx)
            premium = self._looks_premium(parser)
            content = self._extract_content(parser, ctx)
            if premium:
                if ctx.stop_on_premium:
                    raise PremiumReached(number=parsed_number, title=title)
                current_url = next_url
                continue
            if not content.strip():
                raise ScrapeError("Novel543 returned no chapter text; the page may be blocked or its layout changed.")
            if pending is not None:
                if not self._is_continuation(pending.url, current_url):
                    raise ScrapeError("Novel543 returned an inconsistent split-chapter sequence.")
                pending.content += "\n\n" + content
                pending.raw_html += "\n" + html
            else:
                if last_number is None:
                    number = parsed_number
                elif parsed_number is not None and parsed_number > last_number:
                    number = parsed_number
                elif any(word in title_clean for word in ("番外", "外传", "外傳", "特別", "插画", "插畫", "感言", "通知", "請假", "请假")):
                    number = round(last_number + 0.01, 2)
                else:
                    number = float(int(last_number) + 1)
                pending = ChapterData(number=number, title=title_clean, content=content, url=current_url, raw_html=html)
                last_number = number
            if not next_url or not self._is_continuation(current_url, next_url):
                yield pending
                count += 1
                pending = None
            current_url = next_url


# ── Adapter registry ──────────────────────────────────────────────────────
ADAPTERS: dict[str, type[BaseAdapter]] = {
    "fenrirealm": FenriRealmAdapter,
    "readhive": ReadhiveAdapter,
    "boti-translations": BotiTranslationAdapter,
    "69shuba": SixtyNineShubaAdapter,
    "wetriedtls": WeTriedTLSAdapter,
    "novel543": Novel543Adapter,
    "dreamy-translations": DreamyTranslationsAdapter,
    "penguin-squad": PenguinSquadAdapter,
    "azurechronicles": AzureChroniclesAdapter,
    "fucknovelpia": FuckNovelpiaAdapter,
    "raw-fucknovelpia": RawFuckNovelpiaAdapter,
}


def get_adapter(name: str | None = None) -> BaseAdapter:
    """Returns the configured site adapter (defaults to settings.SCRAPER_ADAPTER)."""
    key = (name or settings.SCRAPER_ADAPTER or "fenrirealm").lower()
    cls = ADAPTERS.get(key)
    if cls is None:
        raise ValueError(f"Unknown scraper adapter: {key}")
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
            "start_url_hint": cls.start_url_hint,
        })
    return out
