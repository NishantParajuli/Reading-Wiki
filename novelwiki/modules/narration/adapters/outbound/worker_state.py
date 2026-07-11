from __future__ import annotations

from contextlib import asynccontextmanager
import json


class PostgresNarrationWorkerRepository:
    def __init__(self, pool):
        self._pool = pool

    async def create_job(
        self, novel_id, user_id, scope, voice_id, options, active_statuses
    ) -> int:
        dedupe_key = str(options.get("dedupe_key") or "").strip()
        async with self._pool.acquire() as connection:
            async with connection.transaction():
                if dedupe_key:
                    await connection.execute(
                        "SELECT pg_advisory_xact_lock(hashtext($1), hashtext($2));",
                        "tts_job_dedupe", dedupe_key,
                    )
                    existing = await connection.fetchval(
                        """
                        SELECT id FROM tts_jobs
                        WHERE status = ANY($1::text[])
                          AND options->>'dedupe_key' = $2
                        ORDER BY created_at ASC LIMIT 1;
                        """,
                        list(active_statuses), dedupe_key,
                    )
                    if existing is not None:
                        return int(existing)
                return int(await connection.fetchval(
                    """
                    INSERT INTO tts_jobs
                      (novel_id,user_id,scope,voice_id,options,status,stage)
                    VALUES ($1,$2,$3,$4,$5,'queued','queued') RETURNING id;
                    """,
                    novel_id, user_id, scope, voice_id, json.dumps(options),
                ))

    async def get_job(self, job_id: int) -> dict | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow("SELECT * FROM tts_jobs WHERE id=$1;", job_id)
        return dict(row) if row else None

    async def active_chapter_job(self, **criteria) -> dict | None:
        args = [
            list(criteria["active_statuses"]), criteria["novel_id"],
            criteria["voice_id"], criteria["chapter"], str(int(criteria["version"])),
        ]
        user_id = criteria["user_id"]
        user_condition = "options->>'target_user_id' IS NULL"
        if user_id is not None:
            args.append(str(int(user_id)))
            user_condition = f"options->>'target_user_id' = ${len(args)}"
        force_condition = "" if criteria["include_force"] else (
            "AND COALESCE((options->>'force')::boolean, false) = false"
        )
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                f"""
                SELECT * FROM tts_jobs WHERE status=ANY($1::text[])
                  AND novel_id=$2 AND voice_id=$3 AND scope='chapter'
                  AND options->>'target_kind'='chapter_audio'
                  AND options->>'target_chapter'=$4
                  AND options->>'target_content_version'=$5
                  AND {user_condition} {force_condition}
                ORDER BY created_at ASC LIMIT 1;
                """,
                *args,
            )
        return dict(row) if row else None

    async def active_book_job(self, novel_id, voice_id, active_statuses):
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                SELECT * FROM tts_jobs WHERE status=ANY($1::text[])
                  AND novel_id=$2 AND voice_id=$3 AND scope='book'
                ORDER BY created_at ASC LIMIT 1;
                """,
                list(active_statuses), novel_id, voice_id,
            )
        return dict(row) if row else None

    async def update_job(self, job_id: int, fields: dict) -> None:
        if not fields:
            return
        sets, arguments = [], []
        for key, value in fields.items():
            arguments.append(
                json.dumps(value)
                if key in {"progress", "options"} and value is not None else value
            )
            sets.append(f"{key} = ${len(arguments)}")
        arguments.append(job_id)
        async with self._pool.acquire() as connection:
            await connection.execute(
                f"UPDATE tts_jobs SET {', '.join(sets)}, updated_at=now() "
                f"WHERE id=${len(arguments)};",
                *arguments,
            )

    async def cancel_job(self, job_id: int) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute(
                "UPDATE tts_jobs SET status='canceled',stage='canceled',updated_at=now() "
                "WHERE id=$1 AND status IN ('queued','generating');", job_id,
            )

    async def status(self, job_id: int) -> str | None:
        async with self._pool.acquire() as connection:
            return await connection.fetchval(
                "SELECT status FROM tts_jobs WHERE id=$1;", job_id,
            )

    async def load_user(self, user_id: int) -> dict | None:
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow("SELECT * FROM users WHERE id=$1;", user_id)
        return dict(row) if row else None

    async def find_audio(self, **criteria) -> dict | None:
        async with self._pool.acquire() as connection:
            if criteria["user_id"] is None:
                row = await connection.fetchrow(
                    "SELECT * FROM chapter_audio WHERE novel_id=$1 AND chapter=$2 "
                    "AND voice_id=$3 AND content_version=$4 AND user_id IS NULL;",
                    criteria["novel_id"], criteria["number"], criteria["voice_id"],
                    criteria["version"],
                )
            else:
                row = await connection.fetchrow(
                    "SELECT * FROM chapter_audio WHERE novel_id=$1 AND chapter=$2 "
                    "AND voice_id=$3 AND content_version=$4 AND user_id=$5;",
                    criteria["novel_id"], criteria["number"], criteria["voice_id"],
                    criteria["version"], criteria["user_id"],
                )
        return dict(row) if row else None

    async def upsert_audio(self, **audio) -> None:
        async with self._pool.acquire() as connection:
            if audio["user_id"] is None:
                await connection.execute(
                    """
                    INSERT INTO chapter_audio
                      (novel_id,chapter,user_id,voice_id,language,content_version,
                       audio_path,duration_seconds,file_bytes)
                    VALUES ($1,$2,NULL,$3,$4,$5,$6,$7,$8)
                    ON CONFLICT (novel_id,chapter,voice_id,content_version)
                      WHERE user_id IS NULL
                    DO UPDATE SET audio_path=EXCLUDED.audio_path,
                      duration_seconds=EXCLUDED.duration_seconds,
                      file_bytes=EXCLUDED.file_bytes,language=EXCLUDED.language,
                      created_at=now();
                    """,
                    audio["novel_id"], audio["number"], audio["voice_id"],
                    audio["language"], audio["version"], audio["rel"],
                    int(audio["duration"]), int(audio["nbytes"]),
                )
            else:
                await connection.execute(
                    """
                    INSERT INTO chapter_audio
                      (novel_id,chapter,user_id,voice_id,language,content_version,
                       audio_path,duration_seconds,file_bytes)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
                    ON CONFLICT (novel_id,chapter,voice_id,content_version,user_id)
                      WHERE user_id IS NOT NULL
                    DO UPDATE SET audio_path=EXCLUDED.audio_path,
                      duration_seconds=EXCLUDED.duration_seconds,
                      file_bytes=EXCLUDED.file_bytes,language=EXCLUDED.language,
                      created_at=now();
                    """,
                    audio["novel_id"], audio["number"], audio["user_id"],
                    audio["voice_id"], audio["language"], audio["version"],
                    audio["rel"], int(audio["duration"]), int(audio["nbytes"]),
                )

    @asynccontextmanager
    async def target_lock(self, key: str):
        connection = await self._pool.acquire()
        try:
            await connection.execute(
                "SELECT pg_advisory_lock(hashtext($1),hashtext($2));",
                "tts_audio", key,
            )
            yield
        finally:
            try:
                await connection.execute(
                    "SELECT pg_advisory_unlock(hashtext($1),hashtext($2));",
                    "tts_audio", key,
                )
            finally:
                await self._pool.release(connection)

    async def requeue_interrupted(self) -> str:
        async with self._pool.acquire() as connection:
            return await connection.execute(
                "UPDATE tts_jobs SET status='queued',stage='requeued after restart' "
                "WHERE status='generating';"
            )

    async def claim_next(self, trigger_statuses):
        async with self._pool.acquire() as connection:
            row = await connection.fetchrow(
                """
                UPDATE tts_jobs j SET status='generating',stage='claimed',updated_at=now()
                WHERE j.id=(SELECT id FROM tts_jobs WHERE status=ANY($1::text[])
                  ORDER BY updated_at ASC FOR UPDATE SKIP LOCKED LIMIT 1)
                RETURNING j.*;
                """,
                list(trigger_statuses),
            )
        return dict(row) if row else None
