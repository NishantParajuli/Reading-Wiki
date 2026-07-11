from __future__ import annotations

import os

from novelwiki.modules.identity.public import Principal
from novelwiki.tts import worker as tts_worker
from novelwiki.tts.chapter_text import resolve_chapter_text
from novelwiki.tts.coverage import shared_audio_coverage


class LegacyChapterTextAdapter:
    async def resolve(self, novel_id: int, chapter: float, user_id: int) -> dict:
        return await resolve_chapter_text(novel_id, chapter, {"id": user_id})


class IdentityNarrationQuota:
    def __init__(self, service):
        self._service = service

    async def check_available(self, principal: Principal, units: int = 1) -> None:
        await self._service.check_available(principal, "tts_chapters", units)


class PostgresNarrationQueries:
    def __init__(self, pool):
        self._pool = pool

    async def book_candidates(
        self, novel_id: int, voice: str, start: float | None, end: float | None
    ) -> list[dict]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT c.number, (a.id IS NOT NULL) AS has_audio
                FROM chapters c
                LEFT JOIN chapter_audio a
                  ON a.novel_id = c.novel_id AND a.chapter = c.number AND a.voice_id = $3
                     AND a.content_version = c.content_version AND a.user_id IS NULL
                WHERE c.novel_id = $1
                  AND (c.kind IS NULL OR c.kind = 'chapter')
                  AND ($2::numeric IS NULL OR c.number >= $2)
                  AND ($4::numeric IS NULL OR c.number <= $4)
                ORDER BY c.number ASC;
                """,
                novel_id, start, voice, end,
            )
        return [dict(row) for row in rows]

    async def shared_audio_chapters(self, novel_id: int, voice: str) -> list[float]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT DISTINCT a.chapter
                FROM chapter_audio a
                JOIN chapters c
                  ON c.novel_id = a.novel_id
                 AND c.number = a.chapter
                 AND c.content_version = a.content_version
                WHERE a.novel_id = $1 AND a.voice_id = $2 AND a.user_id IS NULL
                  AND (c.kind IS NULL OR c.kind = 'chapter')
                ORDER BY a.chapter;
                """,
                novel_id, voice,
            )
        return [float(row["chapter"]) for row in rows]

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
        return await shared_audio_coverage(novel_id)


class LegacyNarrationJobs:
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
