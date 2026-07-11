"""Database lifecycle boundary shared by synchronous CLI transports."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from typing import TypeVar

from novelwiki.platform.database import close_db_pool, init_db_pool

T = TypeVar("T")


def run_cli(operation: Awaitable[T]) -> T:
    async def managed() -> T:
        await init_db_pool()
        try:
            return await operation
        finally:
            await close_db_pool()

    return asyncio.run(managed())
