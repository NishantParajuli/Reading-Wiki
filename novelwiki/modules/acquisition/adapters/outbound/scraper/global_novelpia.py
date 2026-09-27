"""Authenticated Novelpia Global prose, through the website's ordinary reader API.

The refresh cookie is private account state. Chapter tokens are short-lived and
never become source URLs, raw HTML, saved credentials, or error messages.
"""
from __future__ import annotations

import asyncio
import math
import re
import time
from urllib.parse import parse_qs, urlencode, urlsplit

from selectolax.parser import HTMLParser

from .base import BaseAdapter, ChapterData, ScrapeContext, ScrapeError, _chapter_text
from .safe_fetch import SafeFetchError, safe_fetch

SITE = "https://global.novelpia.com"
API = "https://api-global.novelpia.com"
AUTH_MESSAGE = "Novelpia login expired or was rejected. Replace your cookies in Settings → Source accounts, then retry."


def _identity(url: str) -> tuple[str, int]:
    try:
        p = urlsplit(url)
        match = re.fullmatch(r"/(novel|viewer)/([1-9][0-9]*)/?", p.path)
        valid = (p.scheme == "https" and p.hostname == "global.novelpia.com"
                 and p.port in {None, 443} and p.username is None and p.password is None)
    except ValueError:
        valid, match = False, None
    if not valid or not match:
        raise ScrapeError("Use a Novelpia Global https://global.novelpia.com/novel/… or /viewer/… URL.")
    return match[1], int(match[2])


def _positive_int(value, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not re.fullmatch(r"[1-9][0-9]*", str(value)):
        raise ScrapeError(f"Novelpia returned an invalid {label}.")
    return int(value)


def _number(value) -> float:
    try:
        if isinstance(value, bool):
            raise ValueError
        result = float(value)
        if not math.isfinite(result) or result < 0:
            raise ValueError
        return result
    except (TypeError, ValueError):
        raise ScrapeError("Novelpia returned an invalid chapter number.") from None


def _content(data: dict) -> tuple[str, str]:
    parts = []
    for key in ("epi_content", "epi_content2", "epi_content3", "epi_content4"):
        value = data.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise ScrapeError("Novelpia returned an invalid chapter body.")
        if value.strip():
            parts.append(value)
    if not parts:
        raise ScrapeError("Novelpia returned no chapter text; the chapter was not saved.")
    parser = HTMLParser("<html><body>" + "\n".join(parts) + "</body></html>")
    # Do not persist signed images, tracking attributes, account state or scripts.
    text = _chapter_text(parser.body)
    if not text.strip():
        raise ScrapeError("This Novelpia chapter contains no extractable prose; image-only chapters are not supported.")
    from html import escape
    html = "\n".join(f"<p>{escape(p)}</p>" for p in text.split("\n\n"))
    return text, html


class _Reader:
    def __init__(self, ctx: ScrapeContext):
        self.ctx = ctx
        self.token = ""
        self.cookies = []
        now = time.time()
        for cookie in ctx.account_cookies:
            if cookie.get("name") not in {"TKEY", "LOGINKEY", "USERKEY"}:
                continue
            expiry = cookie.get("expires", cookie.get("expirationDate"))
            if expiry is not None and float(expiry) <= now:
                continue
            value = cookie.get("value", "")
            if not isinstance(value, str) or not value or re.search(r"[\x00-\x20\x7f;,]", value):
                raise ScrapeError("Invalid Novelpia cookies. Replace them in Settings → Source accounts.")
            self.cookies.append(f"{cookie['name']}={value}")
        if not any(c.startswith("TKEY=") for c in self.cookies):
            raise ScrapeError("Add fresh Novelpia cookies in Settings → Source accounts before scraping.")

    async def request(self, path: str, params: dict | None = None, *, refresh: bool = True) -> dict:
        url = API + path + ("?" + urlencode(params) if params else "")
        headers = {"Origin": SITE, "Referer": SITE + "/", "Cookie": "; ".join(self.cookies)}
        if self.token:
            headers["Login-At"] = self.token
        # API tokens/explicit cookies must never follow redirects, even to an
        # otherwise public host permitted by an operator's scraper overrides.
        for attempt in range(3):
            try:
                response = await safe_fetch(
                    self.ctx.session, url, source_host="api-global.novelpia.com",
                    require_same_host=True, headers=headers, max_redirects=0,
                    raise_for_status=False,
                )
                break
            except SafeFetchError:
                raise ScrapeError("Novelpia rejected the chapter request or returned an unsafe response. Retry later.") from None
            except Exception:
                if attempt == 2:
                    raise ScrapeError("Could not connect to Novelpia. Retry later; saved chapters are retained.") from None
                await asyncio.sleep(attempt + 1)
        try:
            payload = response.json()
        except (ValueError, UnicodeError):
            if response.status_code == 401:
                if refresh:
                    await self.login()
                    return await self.request(path, params, refresh=False)
                raise ScrapeError(AUTH_MESSAGE) from None
            if response.status_code == 429:
                raise ScrapeError("Novelpia is limiting requests. Wait a while, then retry; saved chapters are retained.") from None
            raise ScrapeError("Novelpia returned an unreadable response. Retry later.") from None
        if response.status_code == 429:
            raise ScrapeError("Novelpia is limiting requests. Wait a while, then retry; saved chapters are retained.")
        if response.status_code == 401 and (not isinstance(payload, dict) or not isinstance(payload.get("result"), dict)):
            if refresh:
                await self.login()
                return await self.request(path, params, refresh=False)
            raise ScrapeError(AUTH_MESSAGE)
        if not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
            raise ScrapeError("Novelpia returned an unexpected chapter response.")
        result = payload["result"]
        if result.get("name") == "AUTH_ERROR" or response.status_code == 401:
            if refresh:
                await self.login()
                return await self.request(path, params, refresh=False)
            raise ScrapeError(AUTH_MESSAGE)
        if str(payload.get("code")) != "0000" or response.status_code >= 400:
            episode = (params or {}).get("episode_no")
            link = f"{SITE}/viewer/{episode}" if isinstance(episode, int) and episode > 0 else SITE
            name, code = result.get("name"), str(payload.get("code"))
            if name == "NOVEL_ERROR" and code in {"0008", "0010"}:
                raise ScrapeError(f"Novelpia requires an ad for this chapter. Open {link}, complete the ad, then retry the scrape. Saved chapters are retained.")
            if name == "NOVEL_ERROR" and code == "0009":
                raise ScrapeError(f"This chapter needs access on Novelpia. Open {link}, unlock it with your account, then retry. Saved chapters are retained.")
            if name in {"AUTH_ERROR", "MEMBER_ERROR"} or path == "/v1/login/refresh":
                raise ScrapeError(AUTH_MESSAGE)
            if response.status_code == 429:
                raise ScrapeError("Novelpia is limiting requests. Wait a while, then retry; saved chapters are retained.")
            # Never echo third-party messages, query tokens or response bodies.
            raise ScrapeError(f"Novelpia could not open this chapter. Check {link} in your browser, then retry.")
        return result

    async def login(self):
        self.token = ""
        result = await self.request("/v1/login/refresh", refresh=False)
        token = result.get("LOGINAT")
        if not isinstance(token, str) or not token or re.search(r"[\x00-\x20\x7f]", token):
            raise ScrapeError(AUTH_MESSAGE)
        self.token = token


class GlobalNovelpiaAdapter(BaseAdapter):
    name = "global-novelpia"
    label = "Novelpia Global (global.novelpia.com)"
    default_language = "en"
    resume_after_checkpoint = True
    allowed_hosts = ["api-global.novelpia.com"]
    start_url_hint = "Paste a /novel/… or /viewer/… URL. Add your Novelpia cookies in Settings → Source accounts first."

    async def crawl(self, ctx: ScrapeContext):
        kind, identity = _identity(ctx.start_url)
        reader = _Reader(ctx)
        await reader.login()
        novel = identity if kind == "novel" else None
        previous = None
        if ctx.resume_after_checkpoint:
            # Saved coordinates are non-secret source metadata. Resume with the
            # navigation endpoint rather than spending access on saved content.
            query = parse_qs(urlsplit(ctx.start_url).query)
            if kind != "viewer" or any(len(query.get(k, [])) != 1 for k in ("tg_novel", "tg_sort", "tg_chapter")):
                raise ScrapeError("Novelpia checkpoint is missing navigation metadata. Re-scrape from the source start to rebuild it.")
            novel = _positive_int(query["tg_novel"][0], "checkpoint novel")
            sort = _positive_int(query["tg_sort"][0], "checkpoint order")
            previous = _number(query["tg_chapter"][0])
            following = await reader.request("/v1/novel/episode/next", {
                "novel_no": novel, "episode_no": identity, "sort_no": sort,
            })
            if "episode_no" not in following:
                raise ScrapeError("Novelpia returned incomplete next-chapter navigation.")
            if following["episode_no"] is None:
                return
            identity = _positive_int(following.get("episode_no"), "next chapter")
        if kind == "novel":
            first = await reader.request("/v1/novel/episode/first", {"novel_no": novel})
            identity = _positive_int(first.get("episode_no"), "first chapter")
        seen = set()
        count = 0
        while ctx.max_chapters is None or count < ctx.max_chapters:
            if identity in seen:
                raise ScrapeError("Novelpia repeated chapter navigation; scraping stopped.")
            seen.add(identity)
            result = await reader.request("/v1/novel/episode", {"episode_no": identity})
            data = result.get("data")
            if not isinstance(data, dict):
                raise ScrapeError("Novelpia did not return chapter metadata.")
            if _positive_int(data.get("episode_no"), "chapter identity") != identity:
                raise ScrapeError("Novelpia returned a different chapter than requested.")
            book = _positive_int(data.get("novel_no"), "novel identity")
            if novel is not None and novel != book:
                raise ScrapeError("Novelpia chapter navigation left the selected novel.")
            novel = book
            number = _number(data.get("epi_num"))
            sort = _positive_int(data.get("sort_no"), "chapter order")
            if previous is not None and number <= previous:
                raise ScrapeError("Novelpia returned repeated or backwards chapter numbers.")
            if data.get("flag_content") not in (None, 0):
                raise ScrapeError("This Novelpia chapter is image-only; this adapter imports prose chapters.")
            ticket = result.get("_t")
            if not isinstance(ticket, str) or not ticket:
                raise ScrapeError("Novelpia did not grant chapter access. Open the chapter on Novelpia, then retry.")
            content_result = await reader.request("/v1/novel/episode/content", {"_t": ticket})
            content_data = content_result.get("data")
            if not isinstance(content_data, dict):
                raise ScrapeError("Novelpia returned an invalid chapter body.")
            text, html = _content(content_data)
            title = data.get("epi_title")
            if not isinstance(title, str) or not title.strip():
                title = f"Chapter {number:g}"
            yield ChapterData(number=number, title=title.strip(), content=text,
                              url=f"{SITE}/viewer/{identity}?" + urlencode({
                                  "tg_novel": novel, "tg_sort": sort, "tg_chapter": str(number),
                              }), raw_html=html)
            count += 1
            previous = number
            if ctx.max_chapters is not None and count >= ctx.max_chapters:
                return
            following = await reader.request("/v1/novel/episode/next", {
                "novel_no": novel, "episode_no": identity, "sort_no": sort,
            })
            if "episode_no" not in following:
                raise ScrapeError("Novelpia returned incomplete next-chapter navigation.")
            if following["episode_no"] is None:
                # Empty result is the site's final-chapter response.
                return
            identity = _positive_int(following["episode_no"], "next chapter")
