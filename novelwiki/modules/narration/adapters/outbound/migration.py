from __future__ import annotations

import os

from novelwiki.modules.identity.public import Principal
from novelwiki.tts import worker as tts_worker
from novelwiki.tts.chapter_text import resolve_chapter_text
from novelwiki.tts.coverage import shared_audio_coverage


class ReadingChapterTextAdapter:
    def __init__(self, reading):
        self._reading = reading

    async def resolve(self, novel_id: int, chapter: float, user_id: int) -> dict:
        return await self._reading.resolve_narration_text(
            novel_id, chapter, user_id
        )


class IdentityNarrationQuota:
    def __init__(self, service):
        self._service = service

    async def check_available(self, principal: Principal, units: int = 1) -> None:
        await self._service.check_available(principal, "tts_chapters", units)


class PostgresNarrationQueries:
    def __init__(self, pool, reading):
        self._pool = pool
        self._reading = reading

    async def book_candidates(
        self, novel_id: int, voice: str, start: float | None, end: float | None
    ) -> list[dict]:
        chapters = await self._reading.prose_chapters(novel_id, start, end)
        versions = {chapter["number"]: chapter["content_version"] for chapter in chapters}
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT chapter,content_version FROM chapter_audio WHERE novel_id=$1 "
                "AND voice_id=$2 AND user_id IS NULL;", novel_id, voice,
            )
        current = {
            float(row["chapter"]) for row in rows
            if versions.get(float(row["chapter"])) == int(row["content_version"])
        }
        return [
            {"number": chapter["number"], "has_audio": chapter["number"] in current}
            for chapter in chapters
        ]

    async def shared_audio_chapters(self, novel_id: int, voice: str) -> list[float]:
        return [
            row["number"] for row in await self.book_candidates(
                novel_id, voice, None, None
            ) if row["has_audio"]
        ]

    async def available_voices(
        self, novel_id: int, chapter: float, content_version: int,
        user_id: int | None,
    ) -> list[str]:
        async with self._pool.acquire() as connection:
            if user_id is None:
                rows = await connection.fetch(
                    """
                    SELECT DISTINCT voice_id FROM chapter_audio
                    WHERE novel_id = $1 AND chapter = $2
                      AND content_version = $3 AND user_id IS NULL
                    ORDER BY voice_id;
                    """,
                    novel_id, chapter, content_version,
                )
            else:
                rows = await connection.fetch(
                    """
                    SELECT DISTINCT voice_id FROM chapter_audio
                    WHERE novel_id = $1 AND chapter = $2
                      AND content_version = $3 AND user_id = $4
                    ORDER BY voice_id;
                    """,
                    novel_id, chapter, content_version, user_id,
                )
        return [str(row["voice_id"]) for row in rows]

    async def coverage(self, novel_id: int) -> dict:
        chapters = await self._reading.prose_chapters(novel_id)
        versions = {chapter["number"]: chapter["content_version"] for chapter in chapters}
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                "SELECT chapter,voice_id,duration_seconds,file_bytes,content_version "
                "FROM chapter_audio WHERE novel_id=$1 AND user_id IS NULL;", novel_id,
            )
        current = [
            row for row in rows
            if versions.get(float(row["chapter"])) == int(row["content_version"])
        ]
        by_chapter, by_voice = {}, {}
        for row in current:
            chapter, voice = float(row["chapter"]), str(row["voice_id"])
            by_chapter.setdefault(chapter, set()).add(voice)
            record = by_voice.setdefault(voice, {"chapters": set(), "duration": 0, "bytes": 0})
            record["chapters"].add(chapter)
            record["duration"] += int(row["duration_seconds"] or 0)
            record["bytes"] += int(row["file_bytes"] or 0)
        voices = [{
            "voice_id": voice, "have": len(record["chapters"]),
            "missing": max(0, len(chapters)-len(record["chapters"])),
            "chapters": sorted(record["chapters"]),
            "duration_seconds": record["duration"], "file_bytes": record["bytes"],
        } for voice, record in sorted(by_voice.items())]
        any_count = len(by_chapter)
        return {
            "prose_chapters": len(chapters), "chapters_with_any_audio": any_count,
            "have": any_count, "missing_any": max(0, len(chapters)-any_count),
            "missing": max(0, len(chapters)-any_count), "voices": voices,
            "chapters": [{"chapter": chapter, "voices": sorted(items)}
                         for chapter, items in sorted(by_chapter.items())],
        }


class PostgresNarrationJobs:
    async def find_audio(
        self, novel_id: int, chapter: float, voice: str,
        content_version: int, user_id: int | None,
    ) -> dict | None:
        return await tts_worker.find_audio(
            novel_id, chapter, voice, content_version, user_id
        )

    async def find_active_chapter_job(
        self, novel_id: int, chapter: float, voice: str,
        content_version: int, user_id: int | None,
    ) -> dict | None:
        return await tts_worker.find_active_chapter_job(
            novel_id, chapter, voice, content_version, user_id, include_force=True,
        )

    async def find_active_book_job(self, novel_id: int, voice: str) -> dict | None:
        return await tts_worker.find_active_book_job(novel_id, voice)

    def chapter_options(
        self, novel_id: int, chapter: float, voice: str,
        content_version: int, user_id: int | None, force: bool,
    ) -> dict:
        options = tts_worker.chapter_job_options(
            chapter, content_version, user_id, force=force,
        )
        options["dedupe_key"] = tts_worker.chapter_dedupe_key(
            novel_id, chapter, voice, content_version, user_id, force=force,
        )
        return options

    async def create_job(
        self, novel_id: int, user_id: int, scope: str, voice: str, options: dict
    ) -> int:
        return await tts_worker.create_job(
            novel_id, user_id, scope, voice, options=options,
        )

    async def get_job(self, job_id: int) -> dict | None:
        return await tts_worker.get_job(job_id)

    async def cancel_job(self, job_id: int) -> None:
        await tts_worker.cancel_job(job_id)

    async def lookup_for_reader(
        self, novel_id: int, chapter: float, voice: str, user_id: int
    ) -> dict | None:
        return await tts_worker.lookup_for_reader(
            novel_id, chapter, voice, {"id": user_id},
        )

    def absolute_audio_path(self, relative_path: str) -> str:
        return tts_worker.audio_abs(relative_path)


class NarrationSidecar:
    async def list_voices(self) -> list[dict]:
        from novelwiki.modules.narration.adapters.outbound.sidecar import list_voices
        return await list_voices()


class LocalAudioFiles:
    def exists(self, path: str) -> bool:
        return os.path.exists(path)
