import asyncio
from curl_cffi.requests import AsyncSession
from novelwiki.scraper.adapters import get_adapter, ScrapeContext, HEADERS

# CONFIG: Set your custom CSS/XPath selectors here if using 'generic' or 'generic_xpath'
CONFIG = {
    # CSS selectors example:
    # "title_selector": "h1",
    # "content_selector": "div.chapter-content",
    # "next_selector": "a.next"
    
    # XPath selectors example:
    # "title_xpath": "//h1",
    # "content_xpath": "//div[@class='chapter-content']",
    # "next_xpath": "//a[@class='next']/@href"
}

# ADAPTER: Choose from 'fenrirealm', 'generic', 'generic_xpath', 'boti-translations', '69shuba'
ADAPTER_NAME = "69shuba"

# START: The first chapter URL to start scraping from
START = "http://www.69shuba.com/txt/84208/39503023"

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
