from __future__ import annotations

from novelwiki.kernel.errors import Conflict, Forbidden, InvalidOperation, NotFound
from novelwiki.modules.identity.public import Principal

from .dto import AudioFile, BookAudioCommand, ChapterAudioCommand
from .errors import AudioFileGone
from .ports import (
    AudioFilePort, ChapterTextPort, NarrationAccessPort, NarrationJobsPort,
    NarrationQueryPort, NarrationQuotaPort, NarrationSidecarPort,
)


class NarrationService:
    def __init__(
        self, access: NarrationAccessPort, text: ChapterTextPort,
        quota: NarrationQuotaPort, queries: NarrationQueryPort,
        jobs: NarrationJobsPort, sidecar: NarrationSidecarPort,
        files: AudioFilePort, *, default_voice: str,
        enabled: bool, max_batch_chapters: int,
    ):
        self._access = access
        self._text = text
        self._quota = quota
        self._queries = queries
        self._jobs = jobs
        self._sidecar = sidecar
        self._files = files
        self._default_voice = default_voice
        self._enabled = enabled
        self._max_batch_chapters = max_batch_chapters

    def _voice(self, requested: str | None) -> str:
        return (requested or self._default_voice or "").strip()

    @staticmethod
    def _job_view(job: dict) -> dict:
        return {
            "id": int(job["id"]), "novel_id": int(job["novel_id"]),
            "scope": job["scope"], "voice_id": job["voice_id"],
            "status": job["status"], "stage": job.get("stage"),
            "progress": job.get("progress") or {}, "error": job.get("error"),
        }

    async def voices(self) -> dict:
        return {
            "voices": await self._sidecar.list_voices(),
            "default": self._default_voice, "enabled": self._enabled,
        }

    async def generate_chapter(
        self, novel_id: int, number: float, command: ChapterAudioCommand,
        principal: Principal,
    ) -> dict:
        await self._access.require_readable(novel_id, principal)
        voice = self._voice(command.voice_id)
        if not voice:
            raise InvalidOperation("No voice selected.")
        info = await self._text.resolve(novel_id, number, principal.user_id)
        if info["reason"] == "not_found":
            raise NotFound("Chapter not found.")
        if info["reason"] == "untranslated":
            raise Conflict("Translate this chapter before narrating it.")
        if info["reason"] != "ok":
            raise Conflict("This chapter has no readable text to narrate.")
        user_id = principal.user_id if info["is_overlay"] else None
        if not command.force:
            cached = await self._jobs.find_audio(
                novel_id, number, voice, info["content_version"], user_id
            )
            if cached:
                return {
                    "status": "ready", "cached": True,
                    "duration": cached.get("duration_seconds"), "voice_id": voice,
                }
        active = await self._jobs.find_active_chapter_job(
            novel_id, number, voice, info["content_version"], user_id
        )
        if active:
            return {
                "status": "queued", "cached": False,
                "job_id": int(active["id"]), "voice_id": voice,
            }
        await self._quota.check_available(principal, 1)
        options = self._jobs.chapter_options(
            novel_id, number, voice, info["content_version"], user_id,
            bool(command.force),
        )
        job_id = await self._jobs.create_job(
            novel_id, principal.user_id, "chapter", voice, options
        )
        return {
            "status": "queued", "cached": False,
            "job_id": job_id, "voice_id": voice,
        }

    async def generate_book(
        self, novel_id: int, command: BookAudioCommand, principal: Principal
    ) -> dict:
        await self._access.require_readable(novel_id, principal)
        voice = self._voice(command.voice_id)
        if not voice:
            raise InvalidOperation("No voice selected.")
        active = await self._jobs.find_active_book_job(novel_id, voice)
        if active:
            progress = active.get("progress") or {}
            chapters = (active.get("options") or {}).get("chapters") or []
            return {
                "status": "queued", "job_id": int(active["id"]),
                "total": int(progress.get("total") or len(chapters)),
                "already_cached": 0, "capped": False,
                "voice_id": voice, "existing": True,
            }
        cap = self._max_batch_chapters
        want = cap if not command.count or command.count <= 0 else min(int(command.count), cap)
        rows = await self._queries.book_candidates(
            novel_id, voice, command.start, command.end
        )
        if not rows:
            raise NotFound("This novel has no chapters to narrate.")
        already_cached = sum(1 for row in rows if row["has_audio"])
        missing = [float(row["number"]) for row in rows if not row["has_audio"]]
        capped = len(missing) > want
        selected = missing[:want]
        if not selected:
            return {
                "status": "ready", "total": 0,
                "already_cached": already_cached, "capped": False,
                "message": "Every selected chapter is already narrated in this voice.",
            }
        await self._quota.check_available(principal, 1)
        options = {"chapters": selected, "dedupe_key": f"book:{novel_id}:{voice}"}
        job_id = await self._jobs.create_job(
            novel_id, principal.user_id, "book", voice, options
        )
        return {
            "status": "queued", "job_id": job_id, "total": len(selected),
            "already_cached": already_cached, "capped": capped, "voice_id": voice,
        }

    async def book_status(
        self, novel_id: int, voice_id: str | None, principal: Principal
    ) -> dict:
        await self._access.require_readable(novel_id, principal)
        voice = self._voice(voice_id)
        if not voice:
            return {"active": False, "voice_id": voice}
        job = await self._jobs.find_active_book_job(novel_id, voice)
        return {
            "active": bool(job), "voice_id": voice,
            "job": self._job_view(job) if job else None,
        }

    async def audio_chapters(
        self, novel_id: int, voice_id: str | None, principal: Principal
    ) -> dict:
        await self._access.require_readable(novel_id, principal)
        voice = self._voice(voice_id)
        if not voice:
            return {"voice_id": voice, "chapters": []}
        return {
            "voice_id": voice,
            "chapters": await self._queries.shared_audio_chapters(novel_id, voice),
        }

    async def coverage(self, novel_id: int, principal: Principal) -> dict:
        await self._access.require_readable(novel_id, principal)
        return await self._queries.coverage(novel_id)

    async def job(self, job_id: int, principal: Principal) -> dict:
        job = await self._jobs.get_job(job_id)
        if job is None:
            raise NotFound("Job not found.")
        if job.get("user_id") not in (None, principal.user_id) and not principal.is_admin:
            options = job.get("options") or {}
            shared = (
                options.get("target_kind") == "chapter_audio"
                and options.get("target_user_id") is None
            ) or job.get("scope") == "book"
            if not shared:
                raise NotFound("Job not found.")
            try:
                await self._access.require_readable(int(job["novel_id"]), principal)
            except (NotFound, Forbidden):
                raise NotFound("Job not found.")
        return self._job_view(job)

    async def cancel_job(self, job_id: int, principal: Principal) -> dict:
        job = await self._jobs.get_job(job_id)
        if job is None:
            raise NotFound("Job not found.")
        if job.get("user_id") != principal.user_id and not principal.is_admin:
            raise Forbidden("You can't cancel this job.")
        await self._jobs.cancel_job(job_id)
        return self._job_view(await self._jobs.get_job(job_id))

    async def chapter_status(
        self, novel_id: int, number: float, voice_id: str | None,
        principal: Principal,
    ) -> dict:
        await self._access.require_readable(novel_id, principal)
        voice = self._voice(voice_id)
        if not voice:
            return {
                "cached": False, "voice_id": voice, "any_cached": False,
                "available_voices": [],
            }
        info = await self._text.resolve(novel_id, number, principal.user_id)
        if info["reason"] != "ok":
            return {
                "cached": False, "voice_id": voice, "reason": info["reason"],
                "any_cached": False, "available_voices": [],
            }
        user_id = principal.user_id if info["is_overlay"] else None
        row = await self._jobs.find_audio(
            novel_id, number, voice, info["content_version"], user_id
        )
        available = await self._queries.available_voices(
            novel_id, number, info["content_version"], user_id
        )
        if row:
            return {
                "cached": True, "voice_id": voice,
                "duration": row.get("duration_seconds"), "any_cached": True,
                "available_voices": available,
            }
        active = await self._jobs.find_active_chapter_job(
            novel_id, number, voice, info["content_version"], user_id
        )
        return {
            "cached": False, "voice_id": voice,
            "any_cached": bool(available), "available_voices": available,
            "job_id": int(active["id"]) if active else None,
            "job_status": active["status"] if active else None,
        }

    async def chapter_audio(
        self, novel_id: int, number: float, voice_id: str | None,
        principal: Principal,
    ) -> AudioFile:
        await self._access.require_readable(novel_id, principal)
        voice = self._voice(voice_id)
        row = await self._jobs.lookup_for_reader(
            novel_id, number, voice, principal.user_id
        ) if voice else None
        if not row:
            raise NotFound("No audio for this chapter/voice yet.")
        path = self._jobs.absolute_audio_path(row["audio_path"])
        if not self._files.exists(path):
            raise AudioFileGone("Audio file missing (regenerate it).")
        return AudioFile(path)

