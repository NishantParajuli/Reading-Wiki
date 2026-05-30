import httpx
import asyncio
import logging
from selectolax.parser import HTMLParser
from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool, close_db_pool
from novelwiki.scraper.adapters import get_adapter

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

async def scrape_novel(
    start_url: str, 
    force: bool = False, 
    max_chapters: int = None
) -> int:
    """
    Politely scrapes the novel beginning at start_url.
    Follows 'Next' buttons sequentially.
    Is idempotent by default (skips already scraped chapters unless force=True).
    """
    pool = await get_db_pool()
    adapter = get_adapter()
    
    current_url = start_url
    scraped_count = 0
    
    logger.info(f"Starting sequential scrape from: {current_url}")
    
    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=30.0) as client:
        while current_url:
            if max_chapters is not None and scraped_count >= max_chapters:
                logger.info(f"Reached max chapters limit ({max_chapters}). Stopping.")
                break
                
            logger.info(f"Fetching chapter page: {current_url}")
            try:
                response = await client.get(current_url)
                response.raise_for_status()
            except Exception as e:
                logger.error(f"HTTP request error fetching {current_url}: {e}")
                break
                
            parser = HTMLParser(response.text)
            title = adapter.extract_title(parser)
            content = adapter.extract_content(parser)
            next_url = adapter.extract_next_url(parser, current_url)
            
            chapter_num = adapter.extract_chapter_number(current_url, title)
            if chapter_num is None:
                logger.warning(f"Could not extract chapter number for: {title} at {current_url}. Skipping.")
                if not next_url:
                    break
                current_url = next_url
                continue
                
            word_count = len(content.split())
            
            if not content:
                logger.warning(f"No content extracted for chapter {chapter_num} ({title}). Skipping.")
                if not next_url:
                    break
                current_url = next_url
                continue
                
            # Idempotency check & Upsert
            async with pool.acquire() as conn:
                exists = await conn.fetchrow("SELECT number, title FROM chapters WHERE number = $1;", chapter_num)
                
                if exists and not force:
                    logger.info(f"Chapter {chapter_num} ('{exists['title']}') already exists. Skipping.")
                else:
                    await conn.execute(
                        """
                        INSERT INTO chapters (number, title, url, raw_html, clean_text, word_count)
                        VALUES ($1, $2, $3, $4, $5, $6)
                        ON CONFLICT (number) DO UPDATE 
                        SET title = EXCLUDED.title, url = EXCLUDED.url, raw_html = EXCLUDED.raw_html, 
                            clean_text = EXCLUDED.clean_text, word_count = EXCLUDED.word_count, scraped_at = now();
                        """,
                        chapter_num, title, current_url, response.text, content, word_count
                    )
                    logger.info(f"Saved Chapter {chapter_num}: '{title}' ({word_count} words)")
                    scraped_count += 1
            
            if not next_url:
                logger.info("No next chapter URL found. Sequential navigation completed.")
                break
                
            current_url = next_url
            
            # Rate-limiting / Politeness delay
            await asyncio.sleep(settings.SCRAPER_DELAY)
            
    return scraped_count

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m novelwiki.scraper.runner <start_url> [--force] [--max <max_chapters>]")
        sys.exit(1)
        
    start_url = sys.argv[1]
    force = "--force" in sys.argv
    max_ch = None
    if "--max" in sys.argv:
        try:
            idx = sys.argv.index("--max")
            max_ch = int(sys.argv[idx+1])
        except Exception:
            pass
            
    async def main():
        count = await scrape_novel(start_url, force=force, max_chapters=max_ch)
        logger.info(f"Successfully scraped {count} chapters.")
        await close_db_pool()

    asyncio.run(main())
