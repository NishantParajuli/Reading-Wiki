"""Stable dedicated-worker process entrypoint for AI Execution."""

from __future__ import annotations

import asyncio
import logging
import sys

from novelwiki.modules.ai_execution.adapters.inbound import worker as _implementation


async def main() -> None:
    from novelwiki.platform.database import close_db_pool, init_db_pool

    logging.basicConfig(level=logging.INFO)
    await init_db_pool()
    try:
        await _implementation.worker_loop()
    finally:
        await close_db_pool()


if __name__ == "__main__":
    asyncio.run(main())
else:
    # Preserve identity for external monkeypatch/direct-call fixtures.
    sys.modules[__name__] = _implementation
