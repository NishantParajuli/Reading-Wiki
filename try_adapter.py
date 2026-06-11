import asyncio
from curl_cffi.requests import AsyncSession
from novelwiki.scraper.adapters import get_adapter, ScrapeContext, HEADERS

# CONFIG: Additional configuration parameters (if any)
CONFIG = {}

# ADAPTER: Choose from 'fenrirealm', 'readhive', 'boti-translations', '69shuba'
ADAPTER_NAME = "readhive"

# START: The first chapter URL to start scraping from
START = "https://readhive.org/series/85669/0/"

async def main():
    print(f"Starting test scrape using adapter '{ADAPTER_NAME}' from: {START}")
    adapter = get_adapter(ADAPTER_NAME)
    async with AsyncSession(headers=HEADERS) as s:
        ctx = ScrapeContext(
            start_url=START,
            session=s,
            config=CONFIG,
            max_chapters=3,
            stop_on_premium=True
        )
        async for ch in adapter.crawl(ctx):
            print(f"[{ch.number}] {ch.title!r}  {len(ch.content)} chars")
            print("Preview:", ch.content[:200].replace("\n", " "), "\n---")

if __name__ == "__main__":
    asyncio.run(main())
