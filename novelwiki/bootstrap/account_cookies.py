"""Compose encrypted acquisition account settings for HTTP and scrape workers."""
from novelwiki.modules.acquisition.adapters.outbound.account_cookies import (
    CookieCipher, PostgresAccountCookieRepository,
)
from novelwiki.modules.acquisition.application.account_cookies import AccountCookieService
from novelwiki.platform.config import settings
from novelwiki.platform.database import get_db_pool


async def build_account_cookie_repository():
    return PostgresAccountCookieRepository(await get_db_pool(), CookieCipher(settings.SESSION_SECRET))


async def build_account_cookie_service():
    return AccountCookieService(await build_account_cookie_repository())
