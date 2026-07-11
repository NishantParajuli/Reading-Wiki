import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from curl_cffi.requests import AsyncSession
from novelwiki.platform.config import settings
from novelwiki.platform.database import get_db_pool, close_db_pool
from novelwiki.modules.acquisition.adapters.outbound.scraper.adapters import get_adapter, ScrapeContext, PremiumReached, HEADERS
from novelwiki.modules.acquisition.adapters.outbound.scraper.safe_fetch import SafeFetchError, host_from_url, parse_allowed_hosts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _persist_chapter(conn, source: dict, global_number: float, ch, force: bool) -> bool:
    """Upserts one scraped chapter into the novel's global chapter sequence.
    Returns True if a row was written, False if skipped (already present, no force)."""
    from novelwiki.bootstrap.reading_migration import build_reading_ingestion_gateway
    return await (await build_reading_ingestion_gateway()).upsert_ingested_chapter(
        source, global_number, ch, force
    )


async def _resume_url(pool, source_id: int) -> str | None:
    """The URL of the furthest-progressed chapter already scraped by this source, so a
    re-run can jump straight there instead of re-walking every prior chapter page."""
    from novelwiki.bootstrap.reading_migration import build_reading_ingestion_gateway
    return await (await build_reading_ingestion_gateway()).resume_url(source_id)


async def set_source_offset(_connection, source_id: int, new_offset: float) -> int:
    """Compatibility callable; new routes use the named owner-bound workflow directly."""
    from novelwiki.bootstrap.acquisition_routes import build_import_commit_uow_factory
    from novelwiki.workflows.update_source_offset import update_source_offset
    return await update_source_offset(
        await build_import_commit_uow_factory(), source_id, new_offset
    )


async def scrape_source(
    source_id: int,
    force: bool = False,
    max_chapters: int | None = None,
    expected_novel_id: int | None = None,
    cancel_check: Callable[[], Awaitable[None]] | None = None,
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
            if cancel_check is not None:
                await cancel_check()
            async for ch in adapter.crawl(ctx):
                if cancel_check is not None:
                    await cancel_check()
                fallback_local += 1
                local_number = ch.number if ch.number is not None else float(fallback_local)
                global_number = local_number + offset

                async with pool.acquire() as conn:
                    wrote = await _persist_chapter(conn, source, global_number, ch, force)
                if wrote:
                    scraped_count += 1

                if cancel_check is not None:
                    await cancel_check()
                await asyncio.sleep(settings.SCRAPER_DELAY)
        except PremiumReached as p:
            logger.info(f"Stopped at premium boundary (local chapter {p.number}). Scraped {scraped_count} this run.")

    async with pool.acquire() as conn:
        await conn.execute("UPDATE sources SET last_scraped_at = now() WHERE id = $1;", source_id)

    return scraped_count


async def scrape_novel(
    novel_id: int,
    force: bool = False,
    max_chapters: int | None = None,
    cancel_check: Callable[[], Awaitable[None]] | None = None,
) -> int:
    """Scrapes every source of a novel in id order (e.g. the eng source then a raw
    continuation), accumulating into the novel's continuous chapter sequence."""
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        sources = await conn.fetch("SELECT id FROM sources WHERE novel_id = $1 ORDER BY id ASC;", novel_id)
    total = 0
    for s in sources:
        if cancel_check is not None:
            await cancel_check()
        total += await scrape_source(
            int(s["id"]),
            force=force,
            max_chapters=max_chapters,
            expected_novel_id=novel_id,
            cancel_check=cancel_check,
        )
    return total


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m novelwiki.modules.acquisition.adapters.outbound.scraper.runner <source_id> [--force] [--max <max_chapters>]")
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
