"""Application orchestration for durable narration jobs.

The worker transport owns polling.  This service owns the state-machine decisions and
depends only on a small operations port implemented by the inbound/outbound composition.
"""
from __future__ import annotations

from typing import Any, Protocol


class NarrationWorkerOperations(Protocol):
    async def load_user(self, user_id: int | None) -> dict | None: ...
    def spend_allowed(self, user: dict) -> bool: ...
    async def is_canceled(self, job_id: int) -> bool: ...
    async def sidecar_available(self) -> bool: ...
    async def generate_chapter(self, job: dict, user: dict, number: Any) -> str: ...
    async def update_job(self, job_id: int, **fields: Any) -> None: ...
    async def fail_job(self, job_id: int, error: str) -> None: ...
    def chapter_label(self, number: Any) -> str: ...
    async def acquire_generation(self): ...
    def info(self, message: str) -> None: ...
    def exception(self, message: str) -> None: ...


class NarrationWorkerService:
    def __init__(self, operations: NarrationWorkerOperations):
        self._ops = operations

    async def process(self, job: dict) -> None:
        job_id = int(job["id"])
        try:
            user = await self._ops.load_user(job.get("user_id"))
            if user is None:
                await self._ops.fail_job(job_id, "Job has no owner.")
                return
            if not self._ops.spend_allowed(user):
                await self._ops.fail_job(job_id, "Verify your email to generate audiobooks.")
                return
            await self._run(job, user)
        except Exception as exc:
            self._ops.exception(f"TTS job {job_id} crashed.")
            await self._ops.fail_job(job_id, f"{type(exc).__name__}: {exc}")

    async def _run(self, job: dict, user: dict) -> None:
        job_id = int(job["id"])
        chapters = (job.get("options") or {}).get("chapters") or []
        total = len(chapters)
        if total == 0:
            await self._ops.update_job(
                job_id, status="done", stage="nothing to narrate",
                progress={"done": 0, "total": 0},
            )
            return
        if await self._ops.is_canceled(job_id):
            return
        if not await self._ops.sidecar_available():
            await self._ops.fail_job(
                job_id, "TTS sidecar is unavailable. Start it with: docker compose up -d tts"
            )
            return
        if await self._ops.is_canceled(job_id):
            return

        await self._ops.update_job(
            job_id, status="generating", stage="narrating", error=None,
            progress={"done": 0, "total": total},
        )
        self._ops.info(
            f"TTS job {job_id} started: {total} chapter(s), voice={job['voice_id']}."
        )
        done = skipped = 0
        async with await self._ops.acquire_generation():
            for number in chapters:
                if await self._ops.is_canceled(job_id):
                    await self._ops.update_job(
                        job_id, status="canceled", stage="canceled",
                        progress={"done": done, "skipped": skipped, "total": total,
                                  "stopped_reason": "canceled"},
                    )
                    self._ops.info(f"TTS job {job_id} canceled after {done}/{total} chapters.")
                    return
                label = self._ops.chapter_label(number)
                await self._ops.update_job(
                    job_id,
                    progress={"done": done, "skipped": skipped, "total": total,
                              "current_chapter": label},
                )
                self._ops.info(
                    f"TTS job {job_id}: processing chapter {label} ({done + skipped + 1}/{total})."
                )
                result = await self._ops.generate_chapter(job, user, number)
                if result == "quota":
                    await self._ops.update_job(
                        job_id, status="done", stage="monthly TTS quota reached",
                        progress={"done": done, "skipped": skipped, "total": total,
                                  "stopped_reason": "quota"},
                    )
                    self._ops.info(f"TTS job {job_id} stopped on quota after {done}/{total} chapters.")
                    return
                if result in ("cached", "generated"):
                    done += 1
                else:
                    skipped += 1

        await self._ops.update_job(
            job_id, status="done", stage="done",
            progress={"done": done, "skipped": skipped, "total": total},
        )
        self._ops.info(
            f"TTS job {job_id} finished: {done} narrated/cached, {skipped} skipped of {total}."
        )
