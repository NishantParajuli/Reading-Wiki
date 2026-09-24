"""The current PHP catalogue/readers, rather than obsolete WordPress URLs."""
from __future__ import annotations

import math
import re
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit, urlunsplit

from selectolax.parser import HTMLParser

from .base import BaseAdapter, ChapterData, ScrapeContext, ScrapeError


def chapter_identity(url: str) -> tuple[str, str] | None:
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    if len(query.get("hash", [])) != 1 or len(query.get("ch", [])) != 1:
        return None
    book = query.get("hash", [""])[0]
    chapter = query.get("ch", [""])[0]
    if parts.path != "/chapter.php" or not re.fullmatch(r"[a-fA-F0-9]{40}", book):
        return None
    if not re.fullmatch(r"\d+(?:\.\d+)?", chapter) or not math.isfinite(float(chapter)):
        return None
    return book, chapter


def canonical_chapter_url(url: str) -> str:
    identity = chapter_identity(url)
    if identity is None:
        raise ScrapeError("Use a current FuckNovelpia chapter.php?hash=…&ch=… reader URL.")
    parts = urlsplit(url)
    # Navigation signatures are temporary; saved checkpoints must remain reusable.
    return urlunsplit((parts.scheme, parts.netloc, parts.path,
                       urlencode(dict(zip(("hash", "ch"), identity))), ""))


def paragraph_text(node) -> str:
    for child in node.css("script, style, nav, button, iframe, form, .ads"):
        child.decompose()
    for br in node.css("br"):
        br.replace_with("\n")
    paragraphs = []
    for paragraph in node.css("p, pre, li"):
        # Do not duplicate nested list/paragraph content.
        if paragraph.css("p, pre, li")[1:]:
            continue
        text = paragraph.text(strip=False).replace("\u200b", "").strip()
        if text:
            paragraphs.append(text)
    return "\n\n".join(paragraphs)


class FuckNovelpiaAdapter(BaseAdapter):
    name = "fucknovelpia"
    label = "FuckNovelpia (fucknovelpia.com)"
    default_language = "en"
    allowed_hosts = ["fucknovelpia.com", "www.fucknovelpia.com"]
    start_url_hint = "Paste a /novel/… catalogue URL or a chapter.php?hash=…&ch=… reader URL."

    async def crawl(self, ctx: ScrapeContext):
        current = ctx.start_url
        visited = set()
        count = 0
        book_hash = None
        while current:
            if ctx.max_chapters is not None and count >= ctx.max_chapters:
                return
            parts = urlsplit(current)
            try:
                valid_port = parts.port in {None, 80, 443}
            except ValueError:
                valid_port = False
            if (
                parts.scheme not in {"http", "https"} or parts.hostname not in self.allowed_hosts
                or parts.username or parts.password or not valid_port
            ):
                raise ScrapeError("This adapter accepts public fucknovelpia.com URLs only; navigation used an unexpected host or URL.")
            identity = chapter_identity(current)
            if identity is None and not (parts.path.startswith("/novel/") or parts.path == "/novel.php"):
                raise ScrapeError("Use the current novel catalogue or chapter reader URL, not the homepage or an old WordPress link.")
            if identity is not None:
                if book_hash is not None and identity[0] != book_hash:
                    raise ScrapeError("FuckNovelpia navigation left the selected novel.")
                book_hash = identity[0]
            key = canonical_chapter_url(current) if identity else current
            if key in visited:
                raise ScrapeError("FuckNovelpia chapter navigation repeated a page; crawl stopped.")
            visited.add(key)
            html = await ctx.fetch_text(current)
            if html is None:
                raise ScrapeError("Could not load FuckNovelpia. Retry the source later.")
            parser = HTMLParser(html)
            if identity is None:
                links = [urljoin(current, a.attributes.get("href", ""))
                         for a in parser.css("#chapter-list a[href]")]
                current = next((link for link in links if chapter_identity(link)), "")
                if not current:
                    raise ScrapeError("This novel has no readable chapter links in its catalogue.")
                continue
            reader = parser.css_first(".reader")
            if reader is None:
                raise ScrapeError("FuckNovelpia did not return a chapter reader; it may be blocked or its layout changed.")
            heading = reader.css_first("h1, h2") or parser.css_first("h1")
            title = heading.text(strip=True) if heading else f"Chapter {float(identity[1]):g}"
            next_link = parser.css_first("#chapter-next-link")
            next_url = urljoin(current, next_link.attributes.get("href", "")) if next_link else ""
            if next_url:
                next_id = chapter_identity(next_url)
                if not next_id or next_id[0] != book_hash or float(next_id[1]) <= float(identity[1]):
                    raise ScrapeError("FuckNovelpia returned invalid next-chapter navigation.")
                if urlsplit(next_url).hostname not in self.allowed_hosts:
                    raise ScrapeError("FuckNovelpia next chapter uses an unexpected host.")
            content = paragraph_text(reader)
            if not content:
                # Cover/illustration-only catalogue entries are not prose and need no OCR.
                if reader.css_first("img, svg image") is None:
                    raise ScrapeError("FuckNovelpia returned an empty chapter, not a completed crawl.")
            else:
                yield ChapterData(number=float(identity[1]), title=title, content=content,
                                  url=key, raw_html=html)
                count += 1
            current = next_url
