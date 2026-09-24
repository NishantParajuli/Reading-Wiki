"""Check a public source without creating jobs or saving chapter text."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from curl_cffi.requests import AsyncSession

from novelwiki.modules.acquisition.adapters.outbound.scraper.adapters import ADAPTERS, get_adapter
from novelwiki.modules.acquisition.adapters.outbound.scraper.base import (
    HEADERS,
    PremiumReached,
    ScrapeContext,
    ScrapeError,
)
from novelwiki.modules.acquisition.adapters.outbound.scraper.safe_fetch import (
    host_from_url,
    parse_allowed_hosts,
)
from novelwiki.platform.config import settings


def _positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("adapter", choices=sorted(ADAPTERS), help="website adapter to check")
    parser.add_argument("url", help="public start URL accepted by the adapter")
    parser.add_argument("--max", dest="maximum", type=_positive_integer, default=2,
                        help="maximum chapters to check (default: 2)")
    parser.add_argument("--archive-password-env", metavar="NAME",
                        help="read an archive password from this environment variable")
    return parser


async def probe(adapter_name: str, url: str, maximum: int, config: dict) -> int:
    adapter = get_adapter(adapter_name)
    source_host = host_from_url(url)
    allowed_hosts = parse_allowed_hosts(settings.SCRAPER_ALLOWED_HOST_OVERRIDES)
    allowed_hosts.update(parse_allowed_hosts(adapter.allowed_hosts))
    count = 0
    async with AsyncSession(headers=HEADERS) as session:
        context = ScrapeContext(
            start_url=url,
            session=session,
            config=config,
            max_chapters=maximum,
            stop_on_premium=True,
            source_host=source_host,
            allowed_hosts=allowed_hosts,
            require_same_host=settings.SCRAPER_REQUIRE_SAME_HOST,
        )
        try:
            async for chapter in adapter.crawl(context):
                if not chapter.content or not chapter.content.strip():
                    raise ScrapeError("The adapter returned an empty chapter.")
                print(f"[{chapter.number}] {chapter.title!r}: {len(chapter.content)} characters")
                count += 1
                if count >= maximum:
                    break
                await asyncio.sleep(settings.SCRAPER_DELAY)
        except PremiumReached as exc:
            print(f"Premium/locked boundary at chapter {exc.number}; checked {count} free chapter(s).")
            return count
    if not count:
        raise ScrapeError("No chapters were found; check the URL and source availability.")
    print(f"Checked {count} chapter(s). Nothing was saved.")
    return count


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    config = {}
    password = None
    if args.archive_password_env:
        password = os.environ.get(args.archive_password_env)
        if not password:
            print("The archive password environment variable is missing or empty.", file=sys.stderr)
            return 2
        config["archive_password"] = password
    try:
        asyncio.run(probe(args.adapter, args.url, args.maximum, config))
    except KeyboardInterrupt:
        print("Check cancelled.", file=sys.stderr)
        return 130
    except Exception as exc:
        message = str(exc)
        if password:
            message = message.replace(password, "[redacted]")
        print(f"Check failed: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
