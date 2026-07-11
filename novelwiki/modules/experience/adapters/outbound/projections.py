from __future__ import annotations

import re

from novelwiki.modules.identity.public import Principal

_OLD_ASSET_RE = re.compile(r"^/assets/(?P<novel_id>\d+)/(?P<filename>[^/?#]+)$")


def _asset_url(url: str | None, novel_id: int) -> str | None:
    if not url:
        return url
    match = _OLD_ASSET_RE.match(url)
    if not match or int(match.group("novel_id")) != int(novel_id):
        return url
    return f"/api/assets/novels/{novel_id}/{match.group('filename')}"


def _translation_type(has_raw, has_eng) -> str | None:
    if has_raw and has_eng:
        return "raws+translated"
    if has_raw:
        return "raws"
    if has_eng:
        return "translated"
    return None


PROJECTION_TABLES = {
    "library_cards": frozenset({
        "novels", "library_entries", "reading_progress", "chapters", "sources",
    }),
    "novel_detail": frozenset({
        "novels", "chapters", "sources", "reading_progress", "library_entries",
        "chapter_overlays", "import_jobs", "contributions",
    }),
    "discover": frozenset({
        "novels", "users", "library_entries", "chapters", "sources", "chapter_audio",
    }),
    "public_profile": frozenset({
        "users", "library_entries", "novels", "reading_progress", "chapters",
    }),
}


class PostgresExperienceProjectionRepository:
    """The reviewed read-only cross-module projection registry from plan §8.6."""

    def __init__(self, pool):
        self._pool = pool

    async def library_cards(self, principal: Principal) -> list[dict]:
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT n.id, n.title, n.author, n.cover_url, n.description, n.codex_enabled,
                       n.visibility, n.owner_id, le.shelf, n.status_tags,
                       COUNT(c.number) AS chapter_count,
                       MIN(c.number) AS min_chapter, MAX(c.number) AS max_chapter,
                       p.last_chapter, p.max_chapter_read, p.updated_at AS last_read_at,
                       (SELECT bool_or(s.is_raw) FROM sources s WHERE s.novel_id=n.id) AS has_raw,
                       (SELECT bool_or(NOT s.is_raw) FROM sources s WHERE s.novel_id=n.id) AS has_eng,
                       (SELECT MAX(s.last_scraped_at) FROM sources s WHERE s.novel_id=n.id) AS source_updated_at
                FROM novels n
                LEFT JOIN library_entries le ON le.novel_id=n.id AND le.user_id=$1
                LEFT JOIN reading_progress p ON p.novel_id=n.id AND p.user_id=$1
                LEFT JOIN chapters c ON c.novel_id=n.id
                WHERE le.id IS NOT NULL OR n.owner_id=$1
                GROUP BY n.id, le.shelf, p.last_chapter, p.max_chapter_read, p.updated_at
                ORDER BY n.updated_at DESC NULLS LAST, n.id DESC;
                """,
                principal.user_id,
            )
        return [
            {
                "id": int(row["id"]), "title": row["title"], "author": row["author"],
                "cover_url": _asset_url(row["cover_url"], int(row["id"])),
                "description": row["description"], "codex_enabled": row["codex_enabled"],
                "visibility": row["visibility"],
                "is_owner": row["owner_id"] == principal.user_id,
                "can_edit": row["owner_id"] == principal.user_id or principal.is_admin,
                "shelf": row["shelf"], "status_tags": list(row["status_tags"] or []),
                "translation_type": _translation_type(row["has_raw"], row["has_eng"]),
                "chapter_count": int(row["chapter_count"] or 0),
                "min_chapter": float(row["min_chapter"]) if row["min_chapter"] is not None else None,
                "max_chapter": float(row["max_chapter"]) if row["max_chapter"] is not None else None,
                "last_chapter": float(row["last_chapter"]) if row["last_chapter"] is not None else None,
                "max_chapter_read": float(row["max_chapter_read"]) if row["max_chapter_read"] is not None else None,
                "last_read_at": row["last_read_at"].isoformat() if row["last_read_at"] else None,
                "source_updated_at": row["source_updated_at"].isoformat() if row["source_updated_at"] else None,
                "new_chapters": (
                    max(0, int(round(float(row["max_chapter"]) - float(row["max_chapter_read"]))))
                    if row["max_chapter"] is not None and row["max_chapter_read"] is not None else 0
                ),
            }
            for row in rows
        ]

    async def novel_detail(self, novel_id: int, principal: Principal) -> dict | None:
        async with self._pool.acquire() as connection:
            novel = await connection.fetchrow("SELECT * FROM novels WHERE id=$1;", novel_id)
            if novel is None:
                return None
            span = await connection.fetchrow(
                "SELECT COUNT(*) AS count, MIN(number) AS min, MAX(number) AS max "
                "FROM chapters WHERE novel_id=$1;", novel_id,
            )
            sources = await connection.fetch(
                "SELECT id,adapter,start_url,language,is_raw,chapter_offset,label,last_scraped_at "
                "FROM sources WHERE novel_id=$1 ORDER BY id ASC;", novel_id,
            )
            progress = await connection.fetchrow(
                "SELECT * FROM reading_progress WHERE novel_id=$1 AND user_id=$2;",
                novel_id, principal.user_id,
            )
            entry = await connection.fetchrow(
                "SELECT shelf FROM library_entries WHERE novel_id=$1 AND user_id=$2;",
                novel_id, principal.user_id,
            )
            translated = await connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM chapters WHERE novel_id=$1 AND "
                "(is_translated=TRUE OR (original_text IS NOT NULL AND translation_status='done')));",
                novel_id,
            )
            edited = await connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM chapters WHERE novel_id=$1 AND content_version>1) "
                "OR EXISTS (SELECT 1 FROM chapter_overlays WHERE novel_id=$1);", novel_id,
            )
            ocr = await connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM import_jobs WHERE novel_id=$1 AND cost_estimate ? 'pages');",
                novel_id,
            )
            approved = await connection.fetchval(
                "SELECT EXISTS (SELECT 1 FROM contributions WHERE novel_id=$1 AND status='accepted');",
                novel_id,
            )
        has_raw = any(source["is_raw"] for source in sources) if sources else None
        has_eng = any(not source["is_raw"] for source in sources) if sources else None
        imported = any(source["adapter"] in ("epub", "pdf") for source in sources)
        scraped = any(source["adapter"] not in ("epub", "pdf") for source in sources)
        editor = novel["owner_id"] == principal.user_id or principal.is_admin
        return {
            "id": int(novel["id"]), "title": novel["title"], "author": novel["author"],
            "description": novel["description"], "cover_url": _asset_url(novel["cover_url"], novel_id),
            "original_language": novel["original_language"], "codex_enabled": novel["codex_enabled"],
            "visibility": novel["visibility"], "is_owner": novel["owner_id"] == principal.user_id,
            "can_edit": editor,
            "can_suggest_tags": not editor and novel["visibility"] in ("public", "global"),
            "contribution_policy": novel["contribution_policy"],
            "shelf": entry["shelf"] if entry else None,
            "status_tags": list(novel["status_tags"] or []),
            "translation_type": _translation_type(has_raw, has_eng),
            "provenance": {
                "scraped": scraped, "imported": imported, "ocr": bool(ocr),
                "translated": bool(translated), "user_edited": bool(edited),
                "owner_approved": bool(approved),
                "adapters": sorted({source["adapter"] for source in sources}),
            },
            "chapter_count": int(span["count"]),
            "min_chapter": float(span["min"]) if span["min"] is not None else None,
            "max_chapter": float(span["max"]) if span["max"] is not None else None,
            "sources": [
                {
                    "id": int(source["id"]), "adapter": source["adapter"],
                    "start_url": source["start_url"], "language": source["language"],
                    "is_raw": source["is_raw"],
                    "chapter_offset": float(source["chapter_offset"] or 0),
                    "label": source["label"],
                    "last_scraped_at": source["last_scraped_at"].isoformat() if source["last_scraped_at"] else None,
                }
                for source in sources
            ],
            "progress": {
                "last_chapter": float(progress["last_chapter"]) if progress and progress["last_chapter"] is not None else None,
                "max_chapter_read": float(progress["max_chapter_read"]) if progress and progress["max_chapter_read"] is not None else None,
                "scroll_pct": float(progress["scroll_pct"]) if progress and progress["scroll_pct"] is not None else 0,
            },
        }

    async def discover(
        self, principal: Principal, *, q: str | None, language: str | None,
        tag: str | None, translation: str | None, has_codex: bool | None,
        has_audio: bool | None, freshness: str | None, sort: str,
        offset: int, limit: int,
    ) -> dict:
        has_raw_sql = "EXISTS (SELECT 1 FROM sources s WHERE s.novel_id=n.id AND s.is_raw)"
        has_eng_sql = "EXISTS (SELECT 1 FROM sources s WHERE s.novel_id=n.id AND NOT s.is_raw)"
        has_audio_sql = (
            "EXISTS (SELECT 1 FROM chapter_audio a JOIN chapters c "
            "ON c.novel_id=a.novel_id AND c.number=a.chapter "
            "AND c.content_version=a.content_version WHERE a.novel_id=n.id "
            "AND a.user_id IS NULL AND (c.kind IS NULL OR c.kind='chapter'))"
        )
        freshness_sql = "(SELECT MAX(s.last_scraped_at) FROM sources s WHERE s.novel_id=n.id)"
        conditions = [
            "n.visibility IN ('global','public')",
            "n.owner_id IS DISTINCT FROM $1",
            "le.id IS NULL",
        ]
        arguments: list = [principal.user_id]

        def parameter(value) -> str:
            arguments.append(value)
            return f"${len(arguments)}"

        if q:
            conditions.append(f"n.title ILIKE '%' || {parameter(q)} || '%'")
        if language:
            conditions.append(f"n.original_language={parameter(language)}")
        if tag:
            conditions.append(f"{parameter(tag)}=ANY(n.status_tags)")
        if translation == "translated":
            conditions.append(f"({has_eng_sql} AND NOT {has_raw_sql})")
        elif translation == "raws":
            conditions.append(f"({has_raw_sql} AND NOT {has_eng_sql})")
        elif translation in ("raws+translated", "both"):
            conditions.append(f"({has_raw_sql} AND {has_eng_sql})")
        if has_codex:
            conditions.append("n.codex_enabled=TRUE")
        if has_audio:
            conditions.append(has_audio_sql)
        if freshness == "fresh_7d":
            conditions.append(f"{freshness_sql} >= now()-interval '7 days'")
        elif freshness == "fresh_30d":
            conditions.append(f"{freshness_sql} >= now()-interval '30 days'")
        elif freshness == "stale_30d":
            conditions.append(f"{freshness_sql} < now()-interval '30 days'")
        elif freshness == "never_scraped":
            conditions.append(
                "NOT EXISTS (SELECT 1 FROM sources s WHERE s.novel_id=n.id "
                "AND s.last_scraped_at IS NOT NULL)"
            )
        order = {
            "fresh": f"{freshness_sql} DESC NULLS LAST,n.id DESC",
            "title": "n.title ASC",
            "recent": "(n.visibility='global') DESC,n.updated_at DESC NULLS LAST,n.id DESC",
        }.get(sort, "(n.visibility='global') DESC,n.updated_at DESC NULLS LAST,n.id DESC")
        offset = max(0, int(offset))
        limit = max(1, min(int(limit), 100))
        limit_parameter = parameter(limit)
        offset_parameter = parameter(offset)
        sql = f"""
            SELECT n.id,n.title,n.author,n.cover_url,n.description,n.visibility,
                   n.original_language,n.codex_enabled,n.status_tags,
                   u.username AS owner_username,
                   (SELECT COUNT(*) FROM chapters c WHERE c.novel_id=n.id) AS chapter_count,
                   {has_raw_sql} AS has_raw,{has_eng_sql} AS has_eng,
                   {has_audio_sql} AS has_audio,{freshness_sql} AS last_scraped_at,
                   COUNT(*) OVER () AS total_count
            FROM novels n
            LEFT JOIN users u ON u.id=n.owner_id
            LEFT JOIN library_entries le ON le.novel_id=n.id AND le.user_id=$1
            WHERE {' AND '.join(conditions)}
            ORDER BY {order}
            LIMIT {limit_parameter} OFFSET {offset_parameter};
        """
        async with self._pool.acquire() as connection:
            rows = await connection.fetch(sql, *arguments)
        return {
            "items": [
                {
                    "id": int(row["id"]), "title": row["title"], "author": row["author"],
                    "cover_url": _asset_url(row["cover_url"], int(row["id"])),
                    "description": row["description"], "visibility": row["visibility"],
                    "owner_username": row["owner_username"], "language": row["original_language"],
                    "status_tags": list(row["status_tags"] or []),
                    "translation_type": _translation_type(row["has_raw"], row["has_eng"]),
                    "has_codex": bool(row["codex_enabled"]), "has_audio": bool(row["has_audio"]),
                    "last_scraped_at": row["last_scraped_at"].isoformat() if row["last_scraped_at"] else None,
                    "chapter_count": int(row["chapter_count"] or 0),
                }
                for row in rows
            ],
            "total": int(rows[0]["total_count"]) if rows else 0,
            "offset": offset,
            "limit": limit,
        }

    async def public_profile(
        self, username: str, principal: Principal
    ) -> dict | None:
        async with self._pool.acquire() as connection:
            target = await connection.fetchrow(
                "SELECT * FROM users WHERE username=$1;", (username or "").lower()
            )
            if target is None:
                return None
            target_id = int(target["id"])
            include_private = principal.user_id == target_id or principal.is_admin
            stats = await connection.fetchrow(
                """
                SELECT COUNT(*) FILTER (WHERE le.id IS NOT NULL) AS library_count,
                       COUNT(*) FILTER (WHERE le.shelf='reading') AS reading_count,
                       COUNT(*) FILTER (WHERE le.shelf='completed') AS completed_count,
                       COALESCE(SUM(p.max_chapter_read),0) AS chapters_read
                FROM library_entries le JOIN novels n ON n.id=le.novel_id
                LEFT JOIN reading_progress p ON p.novel_id=n.id AND p.user_id=le.user_id
                WHERE le.user_id=$1 AND ($2 OR n.visibility IN ('global','public'));
                """,
                target_id, include_private,
            )
            reading = await connection.fetch(
                """
                SELECT n.id,n.title,n.cover_url,n.visibility,p.last_chapter,
                       p.max_chapter_read,p.updated_at,
                       (SELECT MAX(number) FROM chapters c WHERE c.novel_id=n.id) AS max_chapter
                FROM reading_progress p JOIN novels n ON n.id=p.novel_id
                WHERE p.user_id=$1 AND p.last_chapter IS NOT NULL
                  AND ($2 OR n.visibility IN ('global','public'))
                ORDER BY p.updated_at DESC NULLS LAST LIMIT 8;
                """, target_id, include_private,
            )
            finished = await connection.fetch(
                """
                SELECT n.id,n.title,n.cover_url,n.visibility
                FROM library_entries le JOIN novels n ON n.id=le.novel_id
                WHERE le.user_id=$1 AND le.shelf='completed'
                  AND ($2 OR n.visibility IN ('global','public'))
                ORDER BY le.added_at DESC LIMIT 8;
                """, target_id, include_private,
            )
            published = await connection.fetch(
                """
                SELECT n.id,n.title,n.cover_url,n.visibility,
                       (SELECT COUNT(*) FROM chapters c WHERE c.novel_id=n.id) AS chapter_count
                FROM novels n WHERE n.owner_id=$1 AND n.visibility IN ('public','global')
                ORDER BY n.updated_at DESC NULLS LAST LIMIT 12;
                """, target_id,
            )

        def novel_brief(row) -> dict:
            result = {
                "id": int(row["id"]), "title": row["title"],
                "cover_url": _asset_url(row["cover_url"], int(row["id"])),
                "visibility": row["visibility"],
            }
            if "last_chapter" in row and row["last_chapter"] is not None:
                result["last_chapter"] = float(row["last_chapter"])
                result["max_chapter"] = float(row["max_chapter"]) if row["max_chapter"] is not None else None
            if "chapter_count" in row and row["chapter_count"] is not None:
                result["chapter_count"] = int(row["chapter_count"])
            return result

        profile = {
            "id": target_id, "username": target["username"],
            "display_name": target["display_name"] or target["username"],
            "bio": target["bio"], "avatar_path": target["avatar_path"],
            "avatar_url": "/assets/" + target["avatar_path"] if target["avatar_path"] else None,
            "created_at": target["created_at"].isoformat() if target["created_at"] else None,
            "is_self": principal.user_id == target_id,
            "role": target["role"] if include_private else None,
            "stats": {
                "library_count": int(stats["library_count"] or 0),
                "reading_count": int(stats["reading_count"] or 0),
                "completed_count": int(stats["completed_count"] or 0),
                "chapters_read": int(stats["chapters_read"] or 0),
            },
            "currently_reading": [novel_brief(row) for row in reading],
            "recently_finished": [novel_brief(row) for row in finished],
            "published": [novel_brief(row) for row in published],
        }
        return profile
