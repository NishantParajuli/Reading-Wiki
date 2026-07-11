"""Ordered application lifecycle registry assembled by the composition root."""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass
from typing import Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LifecycleHook:
    name: str
    start: Callable[[], object] | None = None
    stop: Callable[[], object] | None = None
    fatal_start: bool = False
    start_error: str = "Startup hook failed"
    stop_error: str = "Shutdown hook failed"
    shutdown_order: int = 0


async def _invoke(callback: Callable[[], object] | None) -> None:
    if callback is None:
        return
    result = callback()
    if inspect.isawaitable(result):
        await result


class ApplicationLifecycle:
    def __init__(self, hooks: list[LifecycleHook]):
        names = [hook.name for hook in hooks]
        if len(names) != len(set(names)):
            raise ValueError("Lifecycle hook names must be unique")
        self._hooks = tuple(hooks)

    @property
    def startup_order(self) -> tuple[str, ...]:
        return tuple(hook.name for hook in self._hooks)

    @property
    def shutdown_order(self) -> tuple[str, ...]:
        return tuple(
            hook.name
            for hook in sorted(
                (item for item in self._hooks if item.stop is not None),
                key=lambda item: item.shutdown_order,
            )
        )

    async def start(self) -> None:
        for hook in self._hooks:
            try:
                await _invoke(hook.start)
            except Exception as exc:
                if hook.fatal_start:
                    logger.error("%s: %s", hook.start_error, exc)
                    raise
                logger.warning("%s (continuing): %s", hook.start_error, exc)

    async def stop(self) -> None:
        hooks = sorted(
            (hook for hook in self._hooks if hook.stop is not None),
            key=lambda hook: hook.shutdown_order,
        )
        for hook in hooks:
            try:
                await _invoke(hook.stop)
            except Exception as exc:
                logger.warning("%s: %s", hook.stop_error, exc)


def build_application_lifecycle() -> ApplicationLifecycle:
    from novelwiki.platform.config import settings
    from novelwiki.platform.database import close_db_pool, init_db_pool

    pool_holder: dict[str, object] = {}

    async def initialize_schema():
        from novelwiki.db.schema import init_database
        logger.info("Ensuring database schema exists...")
        await init_database()

    async def initialize_pool():
        logger.info("Initializing database connection pool...")
        pool_holder["pool"] = await init_db_pool()

    async def cleanup_identity():
        from novelwiki.modules.identity.adapters.outbound.maintenance import (
            cleanup_expired_identity_state,
        )
        await cleanup_expired_identity_state(pool_holder["pool"])

    async def migrate_multiuser():
        from novelwiki.db.migrate_multiuser import maybe_migrate
        await maybe_migrate()

    def start_import_worker():
        from novelwiki.modules.acquisition.adapters.inbound.worker import start_worker
        start_worker()

    async def stop_import_worker():
        from novelwiki.modules.acquisition.adapters.inbound.worker import stop_worker
        await stop_worker()

    def start_tts_worker():
        from types import SimpleNamespace

        from novelwiki.modules.identity.adapters.outbound import quota_compat
        from novelwiki.modules.narration.adapters.inbound.worker import (
            configure_worker_runtime,
            start_worker,
        )
        from novelwiki.modules.narration.adapters.outbound import sidecar
        from novelwiki.bootstrap.narration_worker import build_narration_worker_state
        from novelwiki.bootstrap.reading_migration import build_reading_narration_gateway

        async def resolve_chapter_text(novel_id, number, user):
            gateway = await build_reading_narration_gateway()
            return await gateway.resolve_narration_text(
                novel_id, number, int(user["id"]) if isinstance(user, dict) else None
            )

        configure_worker_runtime(SimpleNamespace(
            quota=quota_compat,
            resolve_chapter_text=resolve_chapter_text,
            tts_client=sidecar,
            worker_state_factory=build_narration_worker_state,
        ))
        start_worker()

    async def stop_tts_worker():
        from novelwiki.modules.narration.adapters.inbound.worker import stop_worker
        await stop_worker()

    def start_jobs_worker():
        from types import SimpleNamespace

        from novelwiki.bootstrap.work_worker import build_worker_state_service
        from novelwiki.bootstrap.workers import build_api_worker_registry
        from novelwiki.modules.work.adapters.inbound.worker import (
            configure_worker_runtime,
            start_worker,
        )
        from novelwiki.modules.work.adapters.outbound import postgres
        from novelwiki.modules.work.adapters.outbound.claims import claim_next

        configure_worker_runtime(SimpleNamespace(
            claim_next=claim_next,
            registry_factory=build_api_worker_registry,
            service=postgres,
            worker_state_factory=build_worker_state_service,
        ))
        start_worker()

    async def stop_jobs_worker():
        from novelwiki.modules.work.adapters.inbound.worker import stop_worker
        await stop_worker()

    async def check_agy_worker():
        if not settings.AGY_ENABLED:
            return
        from novelwiki.modules.ai_execution.adapters.outbound.policy import worker_available
        if not await worker_available():
            logger.warning(
                "AGY_ENABLED is true, but no recent healthy dedicated AGY worker heartbeat "
                "exists. AGY jobs may remain queued until the host worker recovers."
            )

    async def close_pool():
        logger.info("Closing database connection pool...")
        await close_db_pool()

    return ApplicationLifecycle([
        LifecycleHook(
            "schema", initialize_schema, start_error="Schema init at startup failed"
        ),
        LifecycleHook(
            "database_pool", initialize_pool, close_pool, fatal_start=True,
            start_error="Database pool initialization failed",
            stop_error="Error closing database pool", shutdown_order=40,
        ),
        LifecycleHook(
            "identity_cleanup", cleanup_identity,
            start_error="Auth cleanup at startup failed",
        ),
        LifecycleHook(
            "multiuser_migration", migrate_multiuser, fatal_start=True,
            start_error="Multi-user migration at startup failed",
        ),
        LifecycleHook(
            "import_worker", start_import_worker, stop_import_worker,
            start_error="Could not start the import worker",
            stop_error="Error stopping import worker", shutdown_order=10,
        ),
        LifecycleHook(
            "tts_worker", start_tts_worker, stop_tts_worker,
            start_error="Could not start the TTS worker",
            stop_error="Error stopping TTS worker", shutdown_order=20,
        ),
        LifecycleHook(
            "jobs_worker", start_jobs_worker, stop_jobs_worker,
            start_error="Could not start the jobs worker",
            stop_error="Error stopping jobs worker", shutdown_order=30,
        ),
        LifecycleHook(
            "agy_health", check_agy_worker,
            start_error="Could not check dedicated AGY worker health",
        ),
    ])
