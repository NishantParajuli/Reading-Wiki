"""Bounded, in-memory text extraction from the raw site's password-protected ZIPs."""
from __future__ import annotations

import asyncio
import io
import re
import stat
import zipfile
from pathlib import PurePosixPath
from urllib.parse import parse_qs, urljoin, urlsplit, urlunsplit

from charset_normalizer import from_bytes
from selectolax.parser import HTMLParser

from ..importer.parsers.epub import parse_epub
from ..importer.segment import build_plan
from .base import BaseAdapter, ChapterData, ScrapeContext, ScrapeError
from .novelpia import paragraph_text

MAX_ARCHIVE_ENTRIES = 10_000
MAX_ARCHIVE_BYTES = 128 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
_TEXT_SUFFIXES = {".txt", ".html", ".htm", ".xhtml", ".epub"}
_CHAPTER_HEADING = re.compile(
    r"^\s*(?:chapter\s+\d+[^\n]{0,120}|第\s*\d+\s*[章話话回][^\n]{0,120}|\d+\s*[화회][^\n]{0,120})\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _guard_archive(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    entries = archive.infolist()
    if len(entries) > MAX_ARCHIVE_ENTRIES or sum(i.file_size for i in entries) > MAX_ARCHIVE_BYTES:
        raise ScrapeError("RAW archive exceeds the entry or expanded-size limit.")
    for item in entries:
        path = PurePosixPath(item.filename.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or stat.S_ISLNK(item.external_attr >> 16):
            raise ScrapeError("RAW archive contains an unsafe member path.")
        if item.file_size > MAX_MEMBER_BYTES:
            raise ScrapeError("A RAW archive member exceeds the 64 MiB limit.")
    return entries


def _natural_key(name: str):
    return tuple((1, int(part)) if part.isdigit() else (0, part.casefold())
                 for part in re.split(r"(\d+)", name))


def _decode_text(data: bytes) -> str:
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        detected = from_bytes(data).best()
        if detected is None:
            raise ScrapeError("Could not determine the RAW text encoding.") from None
        return str(detected)


def _epub_sections(data: bytes):
    # Existing EPUB parser keeps package/XML safety and spine ordering. Text mode
    # avoids writing images into import-job storage from a scraper process.
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        _guard_archive(archive)
    document = parse_epub(io.BytesIO(data), None)
    emitted = False
    for segment in build_plan(document)["segments"]:
        if not segment["include"] or segment["kind"] not in ("chapter", "interlude"):
            continue
        start, end = segment["block_range"]
        content = "\n\n".join(b.text.strip() for b in document.blocks[start:end + 1]
                              if b.text.strip())
        # Some downloaded books use one plain paragraph for the title page.
        # Exclude only an exact book-title match before any narrative section.
        if not emitted and content.strip() == (document.meta.get("title") or "").strip():
            continue
        if content:
            emitted = True
            yield segment["title"], content


def _text_sections(data: bytes, filename: str):
    text = _decode_text(data).replace("\r\n", "\n").replace("\r", "\n").strip()
    if PurePosixPath(filename).suffix.lower() != ".txt":
        parser = HTMLParser(text)
        node = parser.css_first("body") or parser.root
        title_node = node.css_first("h1, h2")
        title = title_node.text(strip=True) if title_node else PurePosixPath(filename).stem
        text = paragraph_text(node)
        if text:
            yield title, text
        return
    headings = list(_CHAPTER_HEADING.finditer(text))
    if headings:
        for index, heading in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            content = text[heading.end():end].strip()
            if content:
                yield heading.group().strip(), content
    elif text:
        yield PurePosixPath(filename).stem, text


def archive_chapters(data: bytes, password: str, source_url: str,
                     resume_index: int = 1, limit: int | None = None) -> list[ChapterData]:
    """Parse without extracting paths or retaining any password in chapter data."""
    if limit is not None and limit <= 0:
        return []
    chapters = []
    number = 0
    text_bytes = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = _guard_archive(archive)
            if "META-INF/container.xml" in archive.namelist():
                sections = [_epub_sections(data)]
            else:
                candidates = [i for i in entries if not i.is_dir()
                              and PurePosixPath(i.filename).suffix.lower() in _TEXT_SUFFIXES
                              and "__MACOSX" not in PurePosixPath(i.filename).parts]
                if not candidates:
                    raise ScrapeError("RAW archive has no EPUB, TXT, or HTML text. Image-only archives need OCR import.")
                if any(i.flag_bits & 1 for i in candidates) and not password:
                    raise ScrapeError("Enter the ZIP password in this RAW source's settings before scraping.")

                def member_sections():
                    for item in sorted(candidates, key=lambda i: _natural_key(i.filename)):
                        with archive.open(item, pwd=password.encode("utf-8") if password else None) as member:
                            content = member.read(MAX_MEMBER_BYTES + 1)
                        if len(content) > MAX_MEMBER_BYTES:
                            raise ScrapeError("RAW archive member exceeds the expanded-size limit.")
                        yield (_epub_sections(content) if item.filename.lower().endswith(".epub")
                               else _text_sections(content, item.filename))
                sections = member_sections()
            for section in sections:
                for title, content in section:
                    number += 1
                    text_bytes += len(content.encode("utf-8"))
                    if text_bytes > MAX_ARCHIVE_BYTES:
                        raise ScrapeError("RAW archive text exceeds the 128 MiB limit.")
                    if number < resume_index:
                        continue
                    chapters.append(ChapterData(number=float(number), title=title, content=content,
                                                url=f"{source_url}#tideglass-chapter={number}"))
                    if limit is not None and len(chapters) >= limit:
                        return chapters
    except ScrapeError:
        raise
    except (RuntimeError, NotImplementedError) as exc:
        raise ScrapeError("Could not unlock the RAW ZIP. Check its password; unsupported ZIP encryption must be unpacked locally.") from exc
    except (zipfile.BadZipFile, KeyError, ValueError, UnicodeError) as exc:
        raise ScrapeError("RAW download is damaged or is not a supported ZIP/EPUB archive.") from exc
    if not chapters and resume_index <= 1:
        raise ScrapeError("RAW archive contains no readable prose chapters.")
    return chapters


class RawFuckNovelpiaAdapter(BaseAdapter):
    name = "raw-fucknovelpia"
    label = "FuckNovelpia RAW archives (raw-fucknovelpia.com)"
    default_language = "ko"
    allowed_hosts = ["raw-fucknovelpia.com", "www.raw-fucknovelpia.com", "assets.raw-fucknovelpia.com"]
    start_url_hint = "Paste a /novel/… catalogue URL and enter its ZIP password. Choose the book’s actual language."

    async def crawl(self, ctx: ScrapeContext):
        parts = urlsplit(ctx.start_url)
        if parts.hostname not in self.allowed_hosts[:2] or not (
            parts.path.startswith("/novel/") or (parts.path == "/novel.php" and parse_qs(parts.query).get("slug"))
        ):
            raise ScrapeError("Use the RAW novel's /novel/… catalogue URL, not its temporary download link.")
        source_url = urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))
        checkpoint = re.fullmatch(r"tideglass-chapter=([1-9]\d*)", parts.fragment)
        resume_index = int(checkpoint[1]) if checkpoint else 1
        if ctx.max_chapters is not None and ctx.max_chapters <= 0:
            return
        html = await ctx.fetch_text(source_url)
        if html is None:
            raise ScrapeError("Could not load the RAW catalogue page.")
        parser = HTMLParser(html)
        download = next((urljoin(source_url, a.attributes["href"]) for a in parser.css("a[href]")
                         if urlsplit(urljoin(source_url, a.attributes["href"])).path == "/download.php"), None)
        if download is None:
            raise ScrapeError("No RAW ZIP download is available for this novel.")
        if urlsplit(download).hostname not in self.allowed_hosts[:2]:
            raise ScrapeError("RAW download link uses an unexpected host.")
        data = await ctx.fetch_bytes(download, raise_errors=True)
        if data is None:
            raise ScrapeError("Could not download the RAW ZIP archive.")
        password = ctx.config.get("archive_password", "")
        if not isinstance(password, str):
            raise ScrapeError("The RAW ZIP password must be text.")
        chapters = await asyncio.to_thread(archive_chapters, data, password, source_url,
                                          resume_index, ctx.max_chapters)
        for chapter in chapters:
            yield chapter
