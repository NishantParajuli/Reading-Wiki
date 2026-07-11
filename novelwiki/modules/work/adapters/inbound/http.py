from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from novelwiki.kernel.errors import NotFound
from novelwiki.modules.work.application import WorkPrincipal, WorkService
from novelwiki.platform.auth import current_user

router = APIRouter()


async def work_service_dependency() -> WorkService:
    raise RuntimeError("WorkService was not wired by the composition root")


def _principal(user: dict) -> WorkPrincipal:
    return WorkPrincipal(int(user["id"]), user.get("role") == "admin")


def _not_found(exc: NotFound):
    raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/jobs")
async def api_list_jobs(
    kind: str | None = None,
    status: str | None = None,
    novel_id: int | None = None,
    user_id: int | None = None,
    active: bool = False,
    limit: int = 100,
    user: dict = Depends(current_user),
    service: WorkService = Depends(work_service_dependency),
):
    """List background jobs. Non-admins are scoped to their own jobs; admins may pass `user_id`
    (and other filters) to inspect any user's jobs."""
    jobs = await service.list_jobs(
        _principal(user),
        requested_user_id=user_id,
        kind=kind,
        status=status,
        novel_id=novel_id,
        active=active,
        limit=limit,
    )
    return {"jobs": jobs}


@router.get("/jobs/{job_id}")
async def api_get_job(
    job_id: int, user: dict = Depends(current_user),
    service: WorkService = Depends(work_service_dependency),
):
    try:
        return await service.get_job(job_id, _principal(user))
    except NotFound as exc:
        _not_found(exc)


@router.post("/jobs/{job_id}/cancel")
async def api_cancel_job(
    job_id: int, user: dict = Depends(current_user),
    service: WorkService = Depends(work_service_dependency),
):
    """Request cancellation. A queued job never starts; a running job stops at its next
    cancellation checkpoint, keeping whatever it already finished. Reserved quota is refunded."""
    try:
        changed = await service.cancel_job(job_id, _principal(user))
    except NotFound as exc:
        _not_found(exc)
    return {"status": "success", "canceled": changed}


__all__ = ["router", "work_service_dependency"]
