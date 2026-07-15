from __future__ import annotations

import json


OPERATIONAL_PROJECTION_TABLES = {
    "home": frozenset({"users", "novels", "library_entries", "reading_progress", "chapters", "sources", "chapter_audio"}),
    "activity": frozenset({"import_jobs", "tts_jobs", "jobs", "ai_execution_runs"}),
    "job_view": frozenset({"jobs", "ai_execution_runs"}),
    "novel_health": frozenset({"novels", "chapters", "entities", "chunks", "sources", "jobs", "import_jobs", "tts_jobs"}),
    "cost_estimate": frozenset({"chapters", "chapter_audio", "quota_usage"}),
    "admin_users": frozenset({"users", "quota_usage", "novels", "user_ai_backend_policies", "jobs"}),
    "admin_agy_health": frozenset({"ai_worker_heartbeats", "jobs", "ai_execution_runs"}),
    "admin_usage": frozenset({"quota_usage", "users", "novels"}),
    "admin_novels": frozenset({"novels", "users", "chapters"}),
    "admin_global_novels": frozenset({"novels", "chapters", "sources"}),
}


class PostgresOperationalProjectionRepository:
    def __init__(self, pool):
        self._pool = pool

    async def generic_activity(self, user_id, active_only, active, limit):
        conditions, arguments = [], []
        if user_id is not None:
            arguments.append(user_id); conditions.append(f"j.user_id=${len(arguments)}")
        if active_only:
            arguments.append(list(active)); conditions.append(f"j.status=ANY(${len(arguments)}::text[])")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        arguments.append(limit)
        async with self._pool.acquire() as connection:
            return await connection.fetch(
                f"""
                SELECT j.*,r.id AS current_run_id,
                  r.plugin_version AS current_plugin_version
                FROM jobs j
                LEFT JOIN LATERAL (
                  SELECT id,plugin_version FROM ai_execution_runs
                  WHERE job_id=j.id ORDER BY created_at DESC LIMIT 1
                ) r ON TRUE
                {where}
                ORDER BY j.created_at DESC LIMIT ${len(arguments)};
                """, *arguments,
            )

    async def import_activity(self, user_id, active_only, terminal, limit):
        conditions, arguments = [], []
        if user_id is not None:
            arguments.append(user_id); conditions.append(f"user_id=${len(arguments)}")
        if active_only:
            arguments.append(list(terminal)); conditions.append(f"status<>ALL(${len(arguments)}::text[])")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        arguments.append(limit)
        async with self._pool.acquire() as connection:
            return await connection.fetch(
                f"SELECT id,novel_id,status,stage,progress,error,original_path,created_at,updated_at "
                f"FROM import_jobs {where} ORDER BY updated_at DESC NULLS LAST,created_at DESC "
                f"LIMIT ${len(arguments)};", *arguments,
            )

    async def tts_activity(self, user_id, active_only, active, limit):
        conditions, arguments = [], []
        if user_id is not None:
            arguments.append(user_id); conditions.append(f"user_id=${len(arguments)}")
        if active_only:
            arguments.append(list(active)); conditions.append(f"status=ANY(${len(arguments)}::text[])")
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        arguments.append(limit)
        async with self._pool.acquire() as connection:
            return await connection.fetch(
                f"SELECT id,novel_id,user_id,scope,voice_id,status,stage,progress,error,created_at,updated_at "
                f"FROM tts_jobs {where} ORDER BY created_at DESC LIMIT ${len(arguments)};",
                *arguments,
            )

    async def home_rows(self, user_id: int, admin: bool):
        async with self._pool.acquire() as connection:
            continuing = await connection.fetch(
                """
                SELECT n.id,n.title,n.author,n.cover_url,n.visibility,n.owner_id,le.shelf,
                  p.last_chapter,p.max_chapter_read,p.scroll_pct,p.updated_at,
                  (SELECT MAX(number) FROM chapters c WHERE c.novel_id=n.id) AS max_chapter,
                  (SELECT c.title FROM chapters c WHERE c.novel_id=n.id AND c.number=p.last_chapter LIMIT 1) AS resume_chapter_title,
                  (SELECT COUNT(DISTINCT a.chapter) FROM chapter_audio a JOIN chapters c
                    ON c.novel_id=a.novel_id AND c.number=a.chapter AND c.content_version=a.content_version
                    WHERE a.novel_id=n.id AND a.user_id IS NULL AND (c.kind IS NULL OR c.kind='chapter')) AS audio_chapters
                FROM reading_progress p JOIN novels n ON n.id=p.novel_id
                LEFT JOIN library_entries le ON le.novel_id=n.id AND le.user_id=$1
                WHERE p.user_id=$1 AND p.last_chapter IS NOT NULL
                  AND (n.visibility IN ('global','public') OR n.owner_id=$1 OR $2)
                ORDER BY p.updated_at DESC NULLS LAST LIMIT 12;
                """, user_id, admin,
            )
            updated = await connection.fetch(
                """
                SELECT n.id,n.title,n.author,n.cover_url,p.max_chapter_read,
                  (SELECT MAX(number) FROM chapters c WHERE c.novel_id=n.id) AS max_chapter,
                  (SELECT COUNT(*) FROM chapters c WHERE c.novel_id=n.id AND c.number>p.max_chapter_read
                    AND (c.kind IS NULL OR c.kind='chapter')) AS new_chapters,
                  (SELECT MAX(s.last_scraped_at) FROM sources s WHERE s.novel_id=n.id) AS source_updated_at
                FROM reading_progress p JOIN novels n ON n.id=p.novel_id
                LEFT JOIN library_entries le ON le.novel_id=n.id AND le.user_id=$1
                WHERE p.user_id=$1 AND p.max_chapter_read IS NOT NULL
                  AND (le.id IS NOT NULL OR n.owner_id=$1)
                  AND (n.visibility IN ('global','public') OR n.owner_id=$1 OR $2)
                  AND EXISTS(SELECT 1 FROM chapters c WHERE c.novel_id=n.id AND c.number>p.max_chapter_read)
                ORDER BY source_updated_at DESC NULLS LAST,n.id DESC LIMIT 8;
                """, user_id, admin,
            )
            newest = await connection.fetch(
                """
                SELECT n.id,n.title,n.author,n.cover_url,n.visibility,n.codex_enabled,
                  u.username AS owner_username,
                  (SELECT COUNT(*) FROM chapters c WHERE c.novel_id=n.id) AS chapter_count,
                  EXISTS(SELECT 1 FROM chapter_audio a JOIN chapters c ON c.novel_id=a.novel_id
                    AND c.number=a.chapter AND c.content_version=a.content_version
                    WHERE a.novel_id=n.id AND a.user_id IS NULL AND (c.kind IS NULL OR c.kind='chapter')) AS has_audio
                FROM novels n LEFT JOIN users u ON u.id=n.owner_id
                WHERE n.visibility IN ('global','public') AND n.owner_id IS DISTINCT FROM $1
                ORDER BY (n.visibility='global') DESC,n.updated_at DESC NULLS LAST,n.id DESC LIMIT 8;
                """, user_id,
            )
        return continuing, updated, newest

    async def novel_health(self, novel_id: int, editor: bool):
        async with self._pool.acquire() as connection:
            metrics = await connection.fetchrow(
                """
                SELECT (SELECT COUNT(*) FROM chapters WHERE novel_id=$1) AS total_chapters,
                  (SELECT MAX(number) FROM chapters WHERE novel_id=$1) AS book_max,
                  (SELECT COUNT(*) FROM entities WHERE novel_id=$1) AS entities_count,
                  (SELECT MAX(chapter) FROM chunks WHERE novel_id=$1) AS codex_max,
                  (SELECT COUNT(*) FROM chapters WHERE novel_id=$1 AND original_text IS NOT NULL
                    AND (content IS NULL OR translation_status<>'done')) AS untranslated,
                  (SELECT MAX(last_scraped_at) FROM sources WHERE novel_id=$1) AS source_last_scraped,
                  (SELECT codex_enabled FROM novels WHERE id=$1) AS codex_enabled;
                """, novel_id,
            )
            errors = []
            if editor:
                errors = await connection.fetch(
                    """
                    SELECT kind,error,updated_at FROM jobs WHERE novel_id=$1 AND status='failed' AND error IS NOT NULL
                    UNION ALL SELECT 'import',error,updated_at FROM import_jobs WHERE novel_id=$1 AND status='failed' AND error IS NOT NULL
                    UNION ALL SELECT 'tts',error,updated_at FROM tts_jobs WHERE novel_id=$1 AND status='failed' AND error IS NOT NULL
                    ORDER BY updated_at DESC LIMIT 5;
                    """, novel_id,
                )
        return metrics, errors

    async def translation_units(self, novel_id, start, end, force):
        async with self._pool.acquire() as connection:
            return int(await connection.fetchval(
                "SELECT COUNT(*) FROM chapters WHERE novel_id=$1 AND original_text IS NOT NULL "
                "AND ($4 OR content IS NULL) AND ($2::numeric IS NULL OR number>=$2) "
                "AND ($3::numeric IS NULL OR number<=$3);", novel_id, start, end, force,
            ) or 0)

    async def audiobook_missing(self, novel_id, start, end, voice):
        async with self._pool.acquire() as connection:
            return int(await connection.fetchval(
                """
                SELECT COUNT(*) FROM chapters c WHERE c.novel_id=$1
                  AND (c.kind IS NULL OR c.kind='chapter')
                  AND ($2::numeric IS NULL OR c.number>=$2)
                  AND ($3::numeric IS NULL OR c.number<=$3)
                  AND NOT EXISTS(SELECT 1 FROM chapter_audio a WHERE a.novel_id=c.novel_id
                    AND a.chapter=c.number AND a.voice_id=$4
                    AND a.content_version=c.content_version AND a.user_id IS NULL);
                """, novel_id, start, end, voice,
            ) or 0)

    async def user_exists(self, user_id: int) -> bool:
        async with self._pool.acquire() as connection:
            return bool(await connection.fetchval("SELECT 1 FROM users WHERE id=$1;", user_id))

    async def recent_smoke(self) -> bool:
        async with self._pool.acquire() as connection:
            return bool(await connection.fetchval(
                "SELECT EXISTS(SELECT 1 FROM audit_events WHERE event='agy.smoke.completed' "
                "AND created_at>now()-interval '10 minutes');"
            ))

    async def admin_users(self, period, query):
        async with self._pool.acquire() as connection:
            return await connection.fetch(
                """
                SELECT u.id,u.email,u.username,u.display_name,u.avatar_path,u.role,u.status,
                  u.email_verified,u.created_at,u.quota_translated_chapters,u.quota_ocr_pages,
                  u.quota_codex_builds,u.quota_tts_chapters,
                  COALESCE(q.translated_chapters,0) AS used_translated,
                  COALESCE(q.ocr_pages,0) AS used_ocr,COALESCE(q.codex_builds,0) AS used_codex,
                  COALESCE(q.tts_chapters,0) AS used_tts,
                  (SELECT COUNT(*) FROM novels n WHERE n.owner_id=u.id) AS novels_owned,
                  p.agy_enabled,p.default_backend,p.agy_workloads,p.fallback_to_api,
                  p.max_concurrent_agy_jobs,p.policy_version,p.notes AS agy_notes,
                  p.updated_at AS agy_updated_at,p.granted_by,
                  (SELECT COUNT(*) FROM jobs j WHERE j.user_id=u.id AND j.execution_backend='agy'
                    AND j.status IN ('queued','running','waiting_provider')) AS agy_active_jobs
                FROM users u LEFT JOIN quota_usage q ON q.user_id=u.id AND q.period=$1
                LEFT JOIN user_ai_backend_policies p ON p.user_id=u.id
                WHERE ($2::text IS NULL OR u.email ILIKE '%'||$2||'%'
                  OR u.username ILIKE '%'||$2||'%' OR u.display_name ILIKE '%'||$2||'%')
                ORDER BY u.created_at DESC LIMIT 500;
                """, period, query,
            )

    async def agy_health(self):
        async with self._pool.acquire() as connection:
            heartbeat = await connection.fetchrow(
                "SELECT * FROM ai_worker_heartbeats WHERE backend='agy' "
                "ORDER BY heartbeat_at DESC LIMIT 1;"
            )
            counts = await connection.fetchrow(
                """
                SELECT count(*) FILTER(WHERE status='queued') AS queued,
                  count(*) FILTER(WHERE status='running') AS running,
                  count(*) FILTER(WHERE status='waiting_provider') AS waiting,
                  min(created_at) FILTER(WHERE status IN ('queued','waiting_provider')) AS oldest
                FROM jobs WHERE execution_backend='agy';
                """
            )
            recent = await connection.fetch(
                "SELECT failure_code,count(*) AS count FROM ai_execution_runs "
                "WHERE backend='agy' AND failure_code IS NOT NULL "
                "AND created_at>now()-interval '7 days' GROUP BY failure_code "
                "ORDER BY count(*) DESC;"
            )
            last_success = await connection.fetchval(
                "SELECT max(finished_at) FROM ai_execution_runs "
                "WHERE backend='agy' AND status='completed';"
            )
        return heartbeat, counts, recent, last_success

    async def admin_usage(self, period):
        async with self._pool.acquire() as connection:
            totals = await connection.fetchrow(
                "SELECT COALESCE(SUM(translated_chapters),0) AS translated_chapters,"
                "COALESCE(SUM(ocr_pages),0) AS ocr_pages,"
                "COALESCE(SUM(codex_builds),0) AS codex_builds,"
                "COUNT(DISTINCT user_id) AS active_users FROM quota_usage WHERE period=$1;",
                period,
            )
            user_count = await connection.fetchval("SELECT COUNT(*) FROM users;")
            novel_count = await connection.fetchval("SELECT COUNT(*) FROM novels;")
            months = await connection.fetch(
                "SELECT period,SUM(translated_chapters) AS translated_chapters,"
                "SUM(ocr_pages) AS ocr_pages,SUM(codex_builds) AS codex_builds "
                "FROM quota_usage WHERE period>=($1::date-INTERVAL '5 months') "
                "GROUP BY period ORDER BY period DESC;", period,
            )
            top = await connection.fetch(
                "SELECT u.id,u.username,u.display_name,q.translated_chapters,q.ocr_pages,q.codex_builds "
                "FROM quota_usage q JOIN users u ON u.id=q.user_id WHERE q.period=$1 "
                "ORDER BY (q.translated_chapters+q.ocr_pages+q.codex_builds) DESC LIMIT 10;",
                period,
            )
        return totals, user_count, novel_count, months, top

    async def admin_novels(self, visibility, query):
        async with self._pool.acquire() as connection:
            return await connection.fetch(
                """
                SELECT n.id,n.title,n.author,n.visibility,n.owner_id,n.updated_at,
                  u.username AS owner_username,
                  (SELECT COUNT(*) FROM chapters c WHERE c.novel_id=n.id) AS chapter_count
                FROM novels n LEFT JOIN users u ON u.id=n.owner_id
                WHERE ($1::text IS NULL OR n.visibility=$1)
                  AND ($2::text IS NULL OR n.title ILIKE '%'||$2||'%')
                ORDER BY n.updated_at DESC NULLS LAST,n.id DESC LIMIT 400;
                """, visibility, query,
            )

    async def global_novels(self):
        async with self._pool.acquire() as connection:
            return await connection.fetch(
                """
                SELECT n.id,n.title,n.codex_enabled,n.updated_at,
                  (SELECT COUNT(*) FROM chapters c WHERE c.novel_id=n.id) AS chapter_count,
                  (SELECT COUNT(*) FROM sources s WHERE s.novel_id=n.id) AS source_count,
                  COALESCE((SELECT bool_or(s.is_raw) FROM sources s WHERE s.novel_id=n.id),FALSE) AS has_raw,
                  (SELECT MAX(s.last_scraped_at) FROM sources s WHERE s.novel_id=n.id) AS last_scraped_at,
                  (SELECT COUNT(*) FROM chapters c WHERE c.novel_id=n.id
                    AND c.original_text IS NOT NULL AND c.content IS NULL) AS untranslated
                FROM novels n WHERE n.visibility='global'
                ORDER BY n.updated_at DESC NULLS LAST,n.id DESC;
                """
            )

    async def job_run_metadata(self, job_ids: set[int]) -> dict[int, dict]:
        if not job_ids:
            return {}
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT DISTINCT ON (job_id)
                  job_id,id,parent_run_id,workload,backend,model,runner_version,
                  plugin_version,plugin_sha256,status,attempt,input_sha256,
                  output_sha256,workspace_relpath,process_group_id,
                  process_started_at,exit_code,failure_code,error_summary,metrics,
                  started_at,finished_at,created_at
                FROM ai_execution_runs WHERE job_id=ANY($1::bigint[])
                ORDER BY job_id,created_at DESC;
                """, sorted(job_ids),
            )
        metadata = {}
        for row in rows:
            metrics = row["metrics"] or {}
            if isinstance(metrics, str):
                metrics = json.loads(metrics)
            metadata[int(row["job_id"])] = {
                "current_run_id": row["id"],
                "current_run_parent_id": row["parent_run_id"],
                "current_run_workload": row["workload"],
                "current_run_backend": row["backend"],
                "current_run_model": row["model"],
                "current_run_runner_version": row["runner_version"],
                "current_plugin_version": row["plugin_version"],
                "current_run_plugin_sha256": row["plugin_sha256"],
                "current_run_status": row["status"],
                "current_run_attempt": row["attempt"],
                "current_run_input_sha256": row["input_sha256"],
                "current_run_output_sha256": row["output_sha256"],
                "current_run_workspace_relpath": row["workspace_relpath"],
                "current_run_process_group_id": row["process_group_id"],
                "current_run_process_started_at": row["process_started_at"],
                "current_run_exit_code": row["exit_code"],
                "current_run_failure_code": row["failure_code"],
                "current_run_error_summary": row["error_summary"],
                "current_run_metrics": metrics,
                "current_run_started_at": row["started_at"],
                "current_run_finished_at": row["finished_at"],
                "current_run_created_at": row["created_at"],
            }
        return metadata
