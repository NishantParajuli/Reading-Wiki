from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from novelwiki.auth.deps import current_user
from novelwiki.jobs import service

router = APIRouter()


def _job_is_owner_or_admin(job: dict, user: dict) -> bool:
    if user.get("role") == "admin":
        return True
    return job.get("user_id") is not None and int(job["user_id"]) == int(user["id"])


async def _require_own_generic_job(job_id: int, user: dict) -> dict:
    job = await service.get_job(job_id)
    if not job or not _job_is_owner_or_admin(job, user):
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@router.get("/jobs")
async def api_list_jobs(
    kind: str | None = None,
    status: str | None = None,
    novel_id: int | None = None,
    user_id: int | None = None,
    active: bool = False,
    limit: int = 100,
    user: dict = Depends(current_user),
):
    """List background jobs. Non-admins are scoped to their own jobs; admins may pass `user_id`
    (and other filters) to inspect any user's jobs."""
    is_admin = user.get("role") == "admin"
    scope_user = None if is_admin else user["id"]
    if is_admin and user_id is not None:
        scope_user = user_id
    jobs = await service.list_jobs(
        user_id=scope_user,
        kind=kind,
        status=status,
        novel_id=novel_id,
        active_only=active,
        limit=limit,
    )
    return {"jobs": [service.job_view(job) for job in jobs]}


@router.get("/jobs/{job_id}")
async def api_get_job(job_id: int, user: dict = Depends(current_user)):
    return service.job_view(await _require_own_generic_job(job_id, user))


@router.post("/jobs/{job_id}/cancel")
async def api_cancel_job(job_id: int, user: dict = Depends(current_user)):
    """Request cancellation. A queued job never starts; a running job stops at its next
    cancellation checkpoint, keeping whatever it already finished. Reserved quota is refunded."""
    await _require_own_generic_job(job_id, user)
    changed = await service.cancel_job(job_id)
    return {"status": "success", "canceled": changed}
