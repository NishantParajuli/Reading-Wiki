import asyncio
import json
import logging
import math
from collections.abc import Awaitable, Callable
from curl_cffi.requests import AsyncSession
from novelwiki.platform.config import settings
from novelwiki.platform.database import get_db_pool
from novelwiki.modules.acquisition.adapters.outbound.scraper.adapters import get_adapter, ScrapeContext, PremiumReached, HEADERS
from novelwiki.modules.acquisition.adapters.outbound.scraper.base import ScrapeError
from novelwiki.modules.acquisition.adapters.outbound.scraper.safe_fetch import SafeFetchError, host_from_url, parse_allowed_hosts

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _persist_chapter(
    conn, source: dict, global_number: float, ch, force: bool, *, runtime
) -> bool:
    """Upserts one scraped chapter into the novel's global chapter sequence.
    Returns True if a row was written, False if skipped (already present, no force)."""
    return await runtime.upsert_ingested_chapter(
        source, global_number, ch, force
    )


async def _resume_url(pool, source_id: int, *, runtime) -> str | None:
    """The URL of the furthest-progressed chapter already scraped by this source, so a
    re-run can jump straight there instead of re-walking every prior chapter page."""
    return await runtime.resume_url(source_id)


async def set_source_offset(
    _connection, source_id: int, new_offset: float, *, runtime
) -> int:
    """Compatibility callable; new routes use the named owner-bound workflow directly."""
    return await runtime.update_source_offset(source_id, new_offset)


async def scrape_source(
    source_id: int,
    force: bool = False,
    max_chapters: int | None = None,
    expected_novel_id: int | None = None,
    cancel_check: Callable[[], Awaitable[None]] | None = None,
    *,
    runtime,
) -> int:
    """Scrapes one source into its novel's global chapter sequence using the source's
    chosen adapter. Source-local chapter numbers are shifted by `chapter_offset` so a
    continuation source lines up after the previous one. Stops cleanly at premium.

    On a re-run we resume from the last chapter already scraped (rather than re-fetching
    every prior page just to skip it), unless `force` re-scrapes from the start."""
    if max_chapters is not None and max_chapters < 1:
        raise ValueError("Maximum chapters must be a positive integer.")
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
        except (ValueError, TypeError) as exc:
            raise ScrapeError("Source configuration is not valid JSON.") from exc
    if cfg is not None and not isinstance(cfg, dict):
        raise ScrapeError("Source configuration must be an object.")
    source["config"] = cfg or {}
    offset = float(source["chapter_offset"] or 0)
    if not math.isfinite(offset):
        raise ScrapeError("Source chapter offset must be finite.")

    adapter = get_adapter(source["adapter"])
    try:
        source_host = host_from_url(source["start_url"])
    except SafeFetchError as e:
        raise ScrapeError("Source has an unsafe start URL.") from e
    allowed_hosts = parse_allowed_hosts(settings.SCRAPER_ALLOWED_HOST_OVERRIDES)
    allowed_hosts.update(parse_allowed_hosts(getattr(adapter, "allowed_hosts", [])))
    allowed_hosts.update(parse_allowed_hosts(source["config"].get("allowed_hosts")))

    start_url = source["start_url"]
    resume = None
    if not force:
        resume = await _resume_url(pool, source_id, runtime=runtime)
        if resume:
            start_url = resume
            logger.info("Resuming source %s from its last saved chapter.", source_id)
    logger.info("Scraping source %s (novel %s, adapter '%s').", source_id, source["novel_id"], source["adapter"])

    scraped_count = 0
    previous_number = None
    async with AsyncSession(headers=HEADERS) as session:
        ctx = ScrapeContext(
            start_url=start_url,
            session=session,
            config=source["config"],
            # The saved checkpoint is inclusive: let the adapter also reach the
            # first unread chapter when the requested limit is one.
            max_chapters=(max_chapters + int(bool(resume))
                          if max_chapters is not None else None),
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
                if not ch.content or not ch.content.strip():
                    raise ScrapeError("Extractor returned an empty chapter; nothing was saved for it.")
                if ch.number is None and resume:
                    raise ScrapeError("Cannot safely resume a chapter without a source number. Check the adapter before retrying.")
                local_number = (float(ch.number) if ch.number is not None
                                else (previous_number + 1 if previous_number is not None else 1.0))
                global_number = local_number + offset
                if not math.isfinite(local_number) or not math.isfinite(global_number):
                    raise ScrapeError("Extractor returned an invalid chapter number.")
                if previous_number is not None and local_number <= previous_number:
                    raise ScrapeError("Extractor returned a repeated or backwards chapter number.")
                previous_number = local_number

                async with pool.acquire() as conn:
                    wrote = await _persist_chapter(
                        conn, source, global_number, ch, force, runtime=runtime
                    )
                if wrote:
                    scraped_count += 1

                if cancel_check is not None:
                    await cancel_check()
                if max_chapters is not None and scraped_count >= max_chapters:
                    break
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
    *,
    runtime,
    scrape_source_operation=None,
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
        operation = scrape_source_operation or scrape_source
        total += await operation(
            int(s["id"]),
            force=force,
            max_chapters=max_chapters,
            expected_novel_id=novel_id,
            cancel_check=cancel_check,
            runtime=runtime,
        )
    return total


if __name__ == "__main__":
    raise SystemExit(
        "This internal adapter requires the application runtime. "
        "Use: uv run python -m novelwiki.cli scrape --help"
    )
