from __future__ import annotations

from dataclasses import dataclass

from novelwiki.kernel.errors import NotFound

from .ports import JobMetadataPort, WorkRepository


@dataclass(frozen=True)
class WorkPrincipal:
    user_id: int
    is_admin: bool = False


class WorkService:
    def __init__(self, repository: WorkRepository, metadata: JobMetadataPort):
        self._repository = repository
        self._metadata = metadata

    async def _enrich(self, jobs: list[dict]) -> list[dict]:
        details = await self._metadata.current({int(job["id"]) for job in jobs})
        for job in jobs:
            job.update(details.get(int(job["id"]), {}))
        return jobs

    async def _owned_job(self, job_id: int, principal: WorkPrincipal) -> dict:
        job = await self._repository.get_job(job_id)
        owned = bool(
            job
            and (
                principal.is_admin
                or (
                    job.get("user_id") is not None
                    and int(job["user_id"]) == principal.user_id
                )
            )
        )
        if not owned:
            raise NotFound("Job not found.")
        return job

    async def list_jobs(
        self, principal: WorkPrincipal, *, kind: str | None = None,
        status: str | None = None, novel_id: int | None = None,
        requested_user_id: int | None = None, active: bool = False,
        limit: int = 100,
    ) -> list[dict]:
        scope = requested_user_id if principal.is_admin else principal.user_id
        jobs = await self._repository.list_jobs(
            user_id=scope, kind=kind, status=status, novel_id=novel_id,
            active_only=active, limit=limit,
        )
        await self._enrich(jobs)
        return [
            self._repository.job_view(job)
            for job in jobs
        ]

    async def get_job(self, job_id: int, principal: WorkPrincipal) -> dict:
        job = await self._owned_job(job_id, principal)
        await self._enrich([job])
        return self._repository.job_view(job)

    async def cancel_job(self, job_id: int, principal: WorkPrincipal) -> bool:
        await self._owned_job(job_id, principal)
        return await self._repository.cancel_job(job_id)
