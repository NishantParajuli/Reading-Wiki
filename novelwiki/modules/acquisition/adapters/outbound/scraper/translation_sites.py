"""Public, server-rendered readers for the English translation sites.

Only published navigation is followed. Account-only content is never requested
through a separate API, and a missing reader is an extraction error, not a paywall.
"""

import json
import math
import re
from collections.abc import AsyncIterator
from urllib.parse import urljoin, urlsplit, urlunsplit

import lxml.html
from selectolax.parser import HTMLParser

from novelwiki.modules.acquisition.adapters.outbound.scraper.base import (
    BaseAdapter,
    ChapterData,
    PremiumReached,
    ScrapeContext,
)


def _reader_text(node, title: str) -> str:
    """Preserve paragraph/line boundaries without splitting inline emphasis."""
    root = lxml.html.fromstring(node.html)
    for unwanted in root.xpath(
        ".//script | .//style | .//button | .//svg | .//nav | .//h1 | "
        ".//*[@hidden or @aria-hidden='true']"
    ):
        unwanted.drop_tree()
    for element in root.iter():
        if element.tag in {"p", "div", "blockquote", "li", "h2", "h3", "br"}:
            element.text = "\n" + (element.text or "")
            element.tail = "\n" + (element.tail or "")
    lines = [re.sub(r"[^\S\n]+", " ", line).strip() for line in root.text_content().splitlines()]
    lines = [line for line in lines if line]
    if lines and lines[0] == title:
        lines.pop(0)
    return "\n\n".join(lines)


def _flight_props(parser: HTMLParser):
    """Read JSON records from Next's public SSR stream without executing scripts."""
    chunks = []
    for script in parser.css("script"):
        match = re.fullmatch(r"\s*self\.__next_f\.push\((.*)\)\s*;?\s*", script.text(), re.S)
        if not match:
            continue
        try:
            chunk = json.loads(match.group(1))
        except (ValueError, TypeError):
            continue
        if isinstance(chunk, list) and len(chunk) == 2 and chunk[0] == 1 and isinstance(chunk[1], str):
            chunks.append(chunk[1])
    decoder = json.JSONDecoder()
    for line in "".join(chunks).splitlines():
        match = re.match(r"^[\da-f]+:(?=[\[{])", line)
        if not match:
            continue
        try:
            record, _ = decoder.raw_decode(line[match.end():])
        except ValueError:
            continue
        pending = [record]
        while pending:
            item = pending.pop()
            if isinstance(item, dict):
                yield item
                pending.extend(item.values())
            elif isinstance(item, list):
                pending.extend(item)


class _TranslationSiteAdapter(BaseAdapter):
    default_language = "en"
    domain: str
    novel_prefix = "novel"
    chapter_segment = r"chapter-(\d+(?:\.\d+)?)(?:-[^/]*)?"
    content_selector: str
    title_selector = "h1"

    def _location(self, url: str) -> tuple[str, float | None]:
        parts = urlsplit(url)
        if (
            parts.scheme not in {"https", "http"}
            or parts.hostname not in {self.domain, "www." + self.domain}
            or parts.username or parts.password or parts.port not in {None, 80, 443}
        ):
            raise ValueError(f"Use a public {self.label} novel or chapter URL.")
        match = re.fullmatch(
            rf"/{self.novel_prefix}/([^/]+)(?:/{self.chapter_segment})?/?", parts.path
        )
        if not match:
            raise ValueError(f"Use a {self.label} novel page or chapter page, not its homepage.")
        number = float(match.group(2)) if match.group(2) is not None else None
        if number is not None and not math.isfinite(number):
            raise ValueError("Invalid chapter number.")
        return match.group(1), number

    def _chapter_link(self, href: str, current: str, series: str) -> tuple[str, float] | None:
        if not href or href.startswith("#"):
            return None
        url = urljoin(current, href)
        try:
            slug, number = self._location(url)
        except ValueError:
            return None
        if slug != series or number is None:
            return None
        parts = urlsplit(url)
        return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", "")), number

    def _first_url(self, parser: HTMLParser, current: str, series: str) -> str:
        chapters = []
        for anchor in parser.css("a[href]"):
            link = self._chapter_link(anchor.attributes["href"], current, series)
            if link is None:
                continue
            if anchor.text(strip=True).lower() in {"start reading", "read"}:
                return link[0]
            chapters.append(link)
        if not chapters:
            raise ValueError(f"No public chapter links found on this {self.label} novel page.")
        return min(chapters, key=lambda item: item[1])[0]

    def _next_url(self, parser: HTMLParser, current: str, series: str, number: float) -> str | None:
        for anchor in parser.css("a[href]"):
            attrs = anchor.attributes
            labels = (
                attrs.get("aria-label", ""), attrs.get("title", ""),
                anchor.text(separator=" ", strip=True),
            )
            is_next = "next" in attrs.get("rel", "").lower().split() or any(
                re.match(r"next\b", label.strip(), re.I) for label in labels
            )
            if not is_next:
                continue
            link = self._chapter_link(attrs["href"], current, series)
            if link and link[1] > number:
                return link[0]
        return None

    def _title(self, parser: HTMLParser, number: float) -> str:
        node = parser.css_first(self.title_selector)
        return node.text(strip=True) if node is not None else f"Chapter {number:g}"

    def _locked(self, parser: HTMLParser, series: str, number: float) -> bool:
        raise NotImplementedError

    async def crawl(self, ctx: ScrapeContext) -> AsyncIterator[ChapterData]:
        series, number = self._location(ctx.start_url)
        if ctx.max_chapters is not None and ctx.max_chapters <= 0:
            return
        current = ctx.start_url
        seen: set[str] = set()
        count = 0
        while current not in seen:
            seen.add(current)
            html = await ctx.fetch_text(current)
            if not html:
                raise RuntimeError(f"Could not fetch the {self.label} chapter or novel page.")
            parser = HTMLParser(html)
            if number is None:
                current = self._first_url(parser, current, series)
                _, number = self._location(current)
                continue
            title = self._title(parser, number)
            next_url = self._next_url(parser, current, series, number)
            if self._locked(parser, series, number):
                if ctx.stop_on_premium:
                    raise PremiumReached(number=number, title=title)
            else:
                node = parser.css_first(self.content_selector)
                content = _reader_text(node, title) if node is not None else ""
                if not content:
                    raise ValueError(f"No readable chapter body found on this {self.label} page.")
                yield ChapterData(number=number, title=title, content=content, url=current, raw_html=html)
                count += 1
                if ctx.max_chapters is not None and count >= ctx.max_chapters:
                    return
            if not next_url:
                return
            current = next_url
            _, number = self._location(current)


class DreamyTranslationsAdapter(_TranslationSiteAdapter):
    name = "dreamy-translations"
    label = "Dreamy Translations"
    domain = "dreamy-translations.com"
    allowed_hosts = [domain, "www." + domain]
    start_url_hint = "Paste a Dreamy novel URL (/novel/slug) or chapter URL (/novel/slug/chapter/1)."
    chapter_segment = r"chapter/(\d+(?:\.\d+)?)"
    content_selector = "article.chapter-content"
    title_selector = 'main div[class~="group/title"] > button'

    def _locked(self, parser: HTMLParser, series: str, number: float) -> bool:
        for props in _flight_props(parser):
            chapter = props.get("chapter")
            if (
                isinstance(chapter, dict) and chapter.get("index") == number
                and props.get("slug") == series and props.get("hasAccess") is False
            ):
                return True
        return False


class PenguinSquadAdapter(_TranslationSiteAdapter):
    name = "penguin-squad"
    label = "Penguin Squad"
    domain = "penguin-squad.com"
    allowed_hosts = [domain, "www." + domain]
    novel_prefix = "novels"
    start_url_hint = "Paste a Penguin Squad novel URL (/novels/slug) or its full chapter URL."
    content_selector = ".reader-content"

    def _locked(self, parser: HTMLParser, series: str, number: float) -> bool:
        premium = any(
            node.text(strip=True).lower() == "premium" for node in parser.css('[data-slot="badge"]')
        )
        return premium and any(
            node.text(strip=True).lower().startswith("unlock this chapter")
            for node in parser.css("h2")
        )


class AzureChroniclesAdapter(_TranslationSiteAdapter):
    name = "azurechronicles"
    label = "Azure Chronicles"
    domain = "azurechronicles.com"
    allowed_hosts = [domain, "www." + domain]
    start_url_hint = "Paste an Azure Chronicles novel URL (/novel/slug/) or chapter URL (/novel/slug/chapter-1/)."
    content_selector = "#ac-r-body"
    title_selector = ".ac-r-chapter-name"

    def _locked(self, parser: HTMLParser, series: str, number: float) -> bool:
        script = parser.css_first("#ac-chapter-reader-js-before")
        if script is None:
            return False
        match = re.search(r"window\.acReaderData\s*=\s*", script.text())
        if match is None:
            return False
        try:
            data, _ = json.JSONDecoder().raw_decode(script.text()[match.end():])
        except ValueError:
            return False
        return isinstance(data, dict) and data.get("canRead") is False
