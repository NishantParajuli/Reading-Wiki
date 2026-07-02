import asyncio
import json
import logging
from curl_cffi.requests import AsyncSession
from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool, close_db_pool
from novelwiki.scraper.adapters import get_adapter, ScrapeContext, PremiumReached, HEADERS
from novelwiki.scraper.safe_fetch import SafeFetchError, host_from_url, parse_allowed_hosts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _persist_chapter(conn, source: dict, global_number: float, ch, force: bool) -> bool:
    """Upserts one scraped chapter into the novel's global chapter sequence.
    Returns True if a row was written, False if skipped (already present, no force)."""
    novel_id = source["novel_id"]
    is_raw = source["is_raw"]
    language = source["language"]

    exists = await conn.fetchrow(
        "SELECT number, title, content, original_text, content_version FROM chapters WHERE novel_id = $1 AND number = $2;",
        novel_id, global_number,
    )
    if exists and not force:
        logger.info(f"Chapter {global_number} ('{exists['title']}') already exists. Skipping.")
        return False

    import re
    if is_raw or language in ("zh", "ja", "ko"):
        word_count = len(re.sub(r"\s+", "", ch.content or ""))
    else:
        word_count = len(ch.content.split())
    if is_raw:
        # Raw source: keep the source-language text; the reader translates on demand.
        original_text, content = ch.content, None
        translation_status, is_translated = "pending", False
    else:
        original_text, content = None, ch.content
        translation_status, is_translated = "none", False

    base_changed = bool(
        exists
        and (
            exists["content"] != content
            or exists["original_text"] != original_text
        )
    )
    new_version = await conn.fetchval(
        """
        INSERT INTO chapters
            (novel_id, number, source_id, title, url, raw_html, original_text, content,
             language, is_translated, translation_status, word_count)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        ON CONFLICT (novel_id, number) DO UPDATE SET
            source_id = EXCLUDED.source_id, title = EXCLUDED.title, url = EXCLUDED.url,
            raw_html = EXCLUDED.raw_html, original_text = EXCLUDED.original_text,
            content = EXCLUDED.content, language = EXCLUDED.language,
            is_translated = EXCLUDED.is_translated, translation_status = EXCLUDED.translation_status,
            word_count = EXCLUDED.word_count, scraped_at = now(),
            content_version = CASE
                WHEN $13 THEN COALESCE(chapters.content_version, 1) + 1
                ELSE COALESCE(chapters.content_version, 1)
            END
        RETURNING content_version;
        """,
        novel_id, global_number, source["id"], ch.title, ch.url, ch.raw_html,
        original_text, content, language, is_translated, translation_status, word_count,
        base_changed,
    )
    if base_changed:
        await conn.execute(
            """
            UPDATE chapter_overlays SET conflict = TRUE, updated_at = now()
            WHERE novel_id = $1 AND chapter = $2 AND base_version < $3;
            """,
            novel_id, global_number, int(new_version or 1),
        )
    logger.info(f"Saved Chapter {global_number}: '{ch.title}' ({word_count} words)")
    return True


async def _resume_url(pool, source_id: int) -> str | None:
    """The URL of the furthest-progressed chapter already scraped by this source, so a
    re-run can jump straight there instead of re-walking every prior chapter page."""
    async with pool.acquire() as conn:
        return await conn.fetchval(
            "SELECT url FROM chapters WHERE source_id = $1 AND url IS NOT NULL ORDER BY number DESC LIMIT 1;",
            source_id,
        )


async def scrape_source(
    source_id: int,
    force: bool = False,
    max_chapters: int | None = None,
    expected_novel_id: int | None = None,
) -> int:
    """Scrapes one source into its novel's global chapter sequence using the source's
    chosen adapter. Source-local chapter numbers are shifted by `chapter_offset` so a
    continuation source lines up after the previous one. Stops cleanly at premium.

    On a re-run we resume from the last chapter already scraped (rather than re-fetching
    every prior page just to skip it), unless `force` re-scrapes from the start."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        source = await conn.fetchrow(
            """
            SELECT id, novel_id, adapter, start_url, config, language, is_raw, chapter_offset
            FROM sources WHERE id = $1;
            """,
            source_id,
        )
    if not source:
        logger.error(f"Source {source_id} not found.")
        return 0

    source = dict(source)
    if expected_novel_id is not None and int(source["novel_id"]) != int(expected_novel_id):
        logger.warning(
            "Refusing to scrape source %s for expected novel %s; source belongs to novel %s.",
            source_id, expected_novel_id, source["novel_id"],
        )
        return 0

    cfg = source.get("config")
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except Exception:
            cfg = {}
    source["config"] = cfg or {}
    offset = float(source["chapter_offset"] or 0)

    adapter = get_adapter(source["adapter"])
    try:
        source_host = host_from_url(source["start_url"])
    except SafeFetchError as e:
        logger.error("Source %s has an unsafe start URL: %s", source_id, e)
        return 0
    allowed_hosts = parse_allowed_hosts(settings.SCRAPER_ALLOWED_HOST_OVERRIDES)
    allowed_hosts.update(parse_allowed_hosts(getattr(adapter, "allowed_hosts", [])))
    allowed_hosts.update(parse_allowed_hosts(source["config"].get("allowed_hosts")))

    start_url = source["start_url"]
    if not force:
        resume = await _resume_url(pool, source_id)
        if resume:
            start_url = resume
            logger.info(f"Resuming source {source_id} from last scraped chapter: {start_url}")
    logger.info(f"Scraping source {source_id} (novel {source['novel_id']}, adapter '{source['adapter']}') from {start_url}")

    scraped_count = 0
    fallback_local = 0  # used only when an adapter can't determine a chapter number
    async with AsyncSession(headers=HEADERS) as session:
        ctx = ScrapeContext(
            start_url=start_url,
            session=session,
            config=source["config"],
            max_chapters=max_chapters,
            stop_on_premium=True,
            source_host=source_host,
            allowed_hosts=allowed_hosts,
            require_same_host=settings.SCRAPER_REQUIRE_SAME_HOST,
        )
        try:
            async for ch in adapter.crawl(ctx):
                fallback_local += 1
                local_number = ch.number if ch.number is not None else float(fallback_local)
                global_number = local_number + offset

                async with pool.acquire() as conn:
                    wrote = await _persist_chapter(conn, source, global_number, ch, force)
                if wrote:
                    scraped_count += 1

                await asyncio.sleep(settings.SCRAPER_DELAY)
        except PremiumReached as p:
            logger.info(f"Stopped at premium boundary (local chapter {p.number}). Scraped {scraped_count} this run.")

    async with pool.acquire() as conn:
        await conn.execute("UPDATE sources SET last_scraped_at = now() WHERE id = $1;", source_id)

    return scraped_count


async def set_source_offset(conn, source_id: int, new_offset: float) -> int:
    """Re-points a source's `chapter_offset` and shifts its already-scraped chapters onto
    the new GLOBAL numbering, so correcting an offset takes effect immediately without a
    re-scrape (e.g. a raw that is one chapter ahead of the translation → offset -1).

    Bookmarks and reading-progress pointers that fall inside the source's chapters move by
    the same delta so they keep pointing at the same text. Returns the number of chapters
    renumbered. Must be called inside a transaction. Raises ValueError if the codex (chunks)
    was already built on the current numbering, since chapter numbers are referenced there
    without ON UPDATE CASCADE."""
    row = await conn.fetchrow("SELECT novel_id, chapter_offset FROM sources WHERE id = $1;", source_id)
    if row is None:
        raise ValueError(f"Source {source_id} not found.")
    novel_id = row["novel_id"]
    delta = float(new_offset) - float(row["chapter_offset"] or 0)

    renumbered = 0
    if delta != 0:
        n_chunks = await conn.fetchval(
            """
            SELECT COUNT(*) FROM chunks c
            JOIN chapters ch ON ch.novel_id = c.novel_id AND ch.number = c.chapter
            WHERE ch.source_id = $1;
            """,
            source_id,
        )
        if n_chunks:
            raise ValueError(
                "This source has codex chunks built on its current chapter numbering; "
                "clear/rebuild the codex before changing the offset."
            )
        # Move reader state that points into this source's chapters BEFORE renumbering them,
        # while the chapters table still holds the OLD numbers used to identify the range.
        # (Bookmarks / reading_progress aren't FK-linked to chapters, so we shift by hand.)
        await conn.execute(
            """
            UPDATE bookmarks SET chapter = chapter + $2
            WHERE novel_id = $3
              AND chapter IN (SELECT number FROM chapters WHERE source_id = $1);
            """,
            source_id, delta, novel_id,
        )
        await conn.execute(
            """
            UPDATE reading_progress SET
                last_chapter = CASE
                    WHEN last_chapter IN (SELECT number FROM chapters WHERE source_id = $1)
                    THEN last_chapter + $2 ELSE last_chapter END,
                max_chapter_read = CASE
                    WHEN max_chapter_read IN (SELECT number FROM chapters WHERE source_id = $1)
                    THEN max_chapter_read + $2 ELSE max_chapter_read END
            WHERE novel_id = $3;
            """,
            source_id, delta, novel_id,
        )
        # Shift through a far range first so a contiguous block never collides with its own
        # not-yet-moved rows (the chapters PK is checked per row, mid-statement). The second
        # step lands on the final numbers and surfaces any real clash with other sources.
        await conn.execute(
            "UPDATE chapters SET number = number + $2 + 1000000 WHERE source_id = $1;",
            source_id, delta,
        )
        status = await conn.execute(
            "UPDATE chapters SET number = number - 1000000 WHERE source_id = $1;",
            source_id,
        )
        try:
            renumbered = int(status.split()[-1])
        except (ValueError, IndexError):
            renumbered = 0

    await conn.execute("UPDATE sources SET chapter_offset = $2 WHERE id = $1;", source_id, new_offset)
    return renumbered


async def scrape_novel(novel_id: int, force: bool = False, max_chapters: int | None = None) -> int:
    """Scrapes every source of a novel in id order (e.g. the eng source then a raw
    continuation), accumulating into the novel's continuous chapter sequence."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        sources = await conn.fetch("SELECT id FROM sources WHERE novel_id = $1 ORDER BY id ASC;", novel_id)
    total = 0
    for s in sources:
        total += await scrape_source(
            int(s["id"]),
            force=force,
            max_chapters=max_chapters,
            expected_novel_id=novel_id,
        )
    return total


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m novelwiki.scraper.runner <source_id> [--force] [--max <max_chapters>]")
        sys.exit(1)

    source_id = int(sys.argv[1])
    force = "--force" in sys.argv
    max_ch = None
    if "--max" in sys.argv:
        try:
            idx = sys.argv.index("--max")
            max_ch = int(sys.argv[idx + 1])
        except Exception:
            pass

    async def main():
        count = await scrape_source(source_id, force=force, max_chapters=max_ch)
        logger.info(f"Successfully scraped {count} chapters.")
        await close_db_pool()

    asyncio.run(main())
