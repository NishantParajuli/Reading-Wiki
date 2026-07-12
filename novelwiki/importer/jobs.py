"""Stable Acquisition job compatibility entrypoint."""

from novelwiki.modules.acquisition.application.import_worker import (
    TRIGGER_STATUSES, _MARKER_RESUME,
)
from novelwiki.bootstrap.acquisition_runtime import build_acquisition_runtime
from novelwiki.modules.acquisition.adapters.inbound.worker import (
    ImportWorkerAdapter, ImportWorkerConfig,
)
from novelwiki.platform.config import settings

_COMPAT_RUNTIME = build_acquisition_runtime()
_COMPAT_WORKER = ImportWorkerAdapter(
    _COMPAT_RUNTIME,
    ImportWorkerConfig(
        lease_timeout_seconds=settings.IMPORT_LEASE_TIMEOUT_SECONDS,
        heartbeat_seconds=settings.IMPORT_WORKER_HEARTBEAT_SECONDS,
        upload_session_ttl_hours=settings.IMPORT_UPLOAD_SESSION_TTL_HOURS,
    ),
)
_WORKER_ID = _COMPAT_WORKER._worker_id


async def _run(name, *args, **kwargs):
    from novelwiki.modules.acquisition.application import import_worker
    return await getattr(import_worker, name)(
        *args, runtime=_COMPAT_RUNTIME, **kwargs
    )


async def create_job(*args, **kwargs):
    return await _run("create_job", *args, **kwargs)


async def get_job(*args, **kwargs):
    return await _run("get_job", *args, **kwargs)


async def list_jobs(*args, **kwargs):
    return await _run("list_jobs", *args, **kwargs)


async def update_job(*args, **kwargs):
    return await _run("update_job", *args, **kwargs)


async def fail_job(*args, **kwargs):
    return await _run("fail_job", *args, **kwargs)


async def touch_job(*args, **kwargs):
    return await _run("touch_job", *args, **kwargs)


async def imports_with_hash(*args, **kwargs):
    return await _run("imports_with_hash", *args, **kwargs)


async def _cleanup_stale_uploads():
    return await _COMPAT_WORKER._cleanup_stale_uploads()


async def _recover_stale_leases():
    return await _COMPAT_WORKER._recover_stale_leases()


async def _claim_next():
    return await _COMPAT_WORKER._claim_next()


async def _renew_lease(job_id, token):
    return await _COMPAT_WORKER._renew_lease(job_id, token)
