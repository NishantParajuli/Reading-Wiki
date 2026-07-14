"""Stable dedicated-worker process entrypoint for AI Execution."""

from __future__ import annotations

import asyncio
import logging
import sys

from novelwiki.modules.ai_execution.adapters.inbound import worker as _implementation
from novelwiki.bootstrap.ai_execution_worker import build_agy_worker_runtime

_implementation.configure_worker_runtime(build_agy_worker_runtime())


async def main() -> None:
    from novelwiki.bootstrap.ai_execution_worker import build_agy_catalog_access
    from novelwiki.bootstrap.work_worker import build_worker_runtime
    from novelwiki.modules.work.adapters.inbound.worker import configure_worker_runtime
    from novelwiki.platform.database import close_db_pool, init_db_pool
    from novelwiki.platform.observability.logging import configure_logging, log_event

    configure_logging()
    configure_worker_runtime(build_worker_runtime())
    await init_db_pool()
    from novelwiki.bootstrap.work import wire_work_quota_finalization
    await wire_work_quota_finalization()
    try:
        try:
            await _implementation.worker_loop(
                catalog_access=await build_agy_catalog_access()
            )
        except Exception:
            log_event(
                logging.getLogger(__name__), logging.CRITICAL, "worker.process_failed",
                "Dedicated AGY worker process failed and will exit.", exc_info=True,
                worker_type="agy", worker_id=_implementation.WORKER_ID,
                execution_backend="agy",
            )
            raise
    finally:
        await close_db_pool()


if __name__ == "__main__":
    asyncio.run(main())
else:
    # Preserve identity for external monkeypatch/direct-call fixtures.
    sys.modules[__name__] = _implementation
