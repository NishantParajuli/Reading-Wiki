"""Private browser RPC. The scraper verifies access again after the browser finishes."""
from __future__ import annotations

import asyncio
import json
from urllib.parse import urlsplit

import httpx

from novelwiki.platform.config import settings
from .base import ScrapeContext

_STATUSES = {"completed", "timeout", "login_required", "unavailable", "busy"}
QUEUE_WAIT_SECONDS = 30
POLL_SECONDS = 0.5


async def _post(client, url: str, payload: dict, headers: dict) -> str:
    async with client.stream("POST", url, json=payload, headers=headers) as response:
        if response.status_code == 429:
            return "busy"
        if response.status_code == 504:
            return "timeout"
        if response.status_code != 200:
            return "unavailable"
        data = bytearray()
        async for chunk in response.aiter_bytes():
            if len(data) + len(chunk) > 4096:
                return "unavailable"
            data.extend(chunk)
        try:
            result = json.loads(data)
        except (ValueError, UnicodeError):
            return "unavailable"
        status = result.get("status") if isinstance(result, dict) else None
        return status if isinstance(status, str) and status in _STATUSES else "unavailable"


async def _cancellable(ctx, operation):
    task = asyncio.create_task(operation)
    try:
        while not task.done():
            if ctx.cancel_check is not None:
                await ctx.cancel_check()
            await asyncio.wait({task}, timeout=POLL_SECONDS)
        # Never advance or commit a chapter after a concurrent cancel request.
        if ctx.cancel_check is not None:
            await ctx.cancel_check()
        return await task
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def complete_ad(ctx: ScrapeContext, episode_id: int) -> str:
    """At most one bounded browser action; no reward API/timer simulation here.

    The host-controlled service URL is deliberately separate from scraped URLs.
    Redirects and ambient proxies are disabled so RPC cookies cannot be forwarded.
    Cancellation closes the HTTP stream, which makes the sidecar close Chromium.
    """
    if not settings.NOVELPIA_BROWSER_ENABLED:
        return "disabled"
    token = settings.NOVELPIA_BROWSER_TOKEN or settings.SIDECAR_AUTH_TOKEN
    url = settings.NOVELPIA_BROWSER_URL.rstrip("/")
    try:
        parsed = urlsplit(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            return "unavailable"
    except ValueError:
        return "unavailable"
    if not token:
        return "unavailable"
    duration = settings.NOVELPIA_BROWSER_TIMEOUT_SECONDS
    payload = {"episode_id": episode_id, "cookies": ctx.account_cookies,
               "timeout_seconds": duration}
    headers = {"X-Tideglass-Sidecar-Token": token}
    loop = asyncio.get_running_loop()
    queue_deadline = loop.time() + QUEUE_WAIT_SECONDS
    if ctx.report_stage is not None:
        await ctx.report_stage("Watching Novelpia ad")
    try:
        async with httpx.AsyncClient(timeout=duration + 5, trust_env=False, follow_redirects=False) as client:
            # This deadline also covers a busy browser followed by one full ad.
            async with asyncio.timeout(QUEUE_WAIT_SECONDS + duration + 5):
                while True:
                    result = await _cancellable(ctx, _post(client, url + "/unlock", payload, headers))
                    if result != "busy":
                        return result
                    if loop.time() >= queue_deadline:
                        return "busy"
                    if ctx.report_stage is not None:
                        await ctx.report_stage("Waiting for Novelpia browser")
                    await _cancellable(ctx, asyncio.sleep(2))
    except (httpx.HTTPError, OSError, ValueError):
        return "unavailable"
    except TimeoutError:
        return "timeout"
