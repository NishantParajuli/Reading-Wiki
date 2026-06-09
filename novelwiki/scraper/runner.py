import asyncio
import json
import logging
from curl_cffi.requests import AsyncSession
from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool, close_db_pool
from novelwiki.scraper.adapters import get_adapter, ScrapeContext, PremiumReached, HEADERS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _persist_chapter(conn, source: dict, global_number: float, ch, force: bool) -> bool:
    """Upserts one scraped chapter into the novel's global chapter sequence.
    Returns True if a row was written, False if skipped (already present, no force)."""
    novel_id = source["novel_id"]
    is_raw = source["is_raw"]
    language = source["language"]

    exists = await conn.fetchrow(
        "SELECT number, title FROM chapters WHERE novel_id = $1 AND number = $2;",
        novel_id, global_number,
    )
    if exists and not force:
        logger.info(f"Chapter {global_number} ('{exists['title']}') already exists. Skipping.")
        return False

    word_count = len(ch.content.split())
    if is_raw:
        # Raw source: keep the source-language text; the reader translates on demand.
        original_text, content = ch.content, None
        translation_status, is_translated = "pending", False
    else:
        original_text, content = None, ch.content
        translation_status, is_translated = "none", False

    await conn.execute(
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
            word_count = EXCLUDED.word_count, scraped_at = now();
        """,
        novel_id, global_number, source["id"], ch.title, ch.url, ch.raw_html,
        original_text, content, language, is_translated, translation_status, word_count,
    )
    logger.info(f"Saved Chapter {global_number}: '{ch.title}' ({word_count} words)")
    return True


async def scrape_source(source_id: int, force: bool = False, max_chapters: int | None = None) -> int:
    """Scrapes one source into its novel's global chapter sequence using the source's
    chosen adapter. Source-local chapter numbers are shifted by `chapter_offset` so a
    continuation source lines up after the previous one. Stops cleanly at premium."""
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
    cfg = source.get("config")
    if isinstance(cfg, str):
        try:
            cfg = json.loads(cfg)
        except Exception:
            cfg = {}
    source["config"] = cfg or {}
    offset = float(source["chapter_offset"] or 0)

    adapter = get_adapter(source["adapter"])
    logger.info(f"Scraping source {source_id} (novel {source['novel_id']}, adapter '{source['adapter']}') from {source['start_url']}")

    scraped_count = 0
    fallback_local = 0  # used only when an adapter can't determine a chapter number
    async with AsyncSession(headers=HEADERS) as session:
        ctx = ScrapeContext(
            start_url=source["start_url"],
            session=session,
            config=source["config"],
            max_chapters=max_chapters,
            stop_on_premium=True,
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


async def scrape_novel(novel_id: int, force: bool = False, max_chapters: int | None = None) -> int:
    """Scrapes every source of a novel in id order (e.g. the eng source then a raw
    continuation), accumulating into the novel's continuous chapter sequence."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        sources = await conn.fetch("SELECT id FROM sources WHERE novel_id = $1 ORDER BY id ASC;", novel_id)
    total = 0
    for s in sources:
        total += await scrape_source(int(s["id"]), force=force, max_chapters=max_chapters)
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
