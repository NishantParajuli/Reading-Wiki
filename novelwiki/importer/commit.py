"""Commit a reviewed plan into real chapters.

This is where the import pipeline rejoins the scraper: every included segment becomes a
``ChapterData`` and is written through the exact same ``_persist_chapter`` path the scraper
uses, so codex + translation work on imported books with zero extra wiring. Images are
promoted from the job's staging dir into the novel's asset dir, the cover autofills the
new novel, and (if the codex is enabled) a background build is kicked over the imported range.

Numbering is finalized here — chapters get their global numbers before any codex runs, so
``set_source_offset`` is never blocked later. New-novel imports start at offset 0; appends
take an offset and abort with a clear error on any collision with existing chapters.
"""
from __future__ import annotations

import asyncio
import json
import logging

from novelwiki.config.settings import settings
from novelwiki.db.connection import get_db_pool
from novelwiki.importer import storage
from novelwiki.importer.render import render_segment

logger = logging.getLogger(__name__)

# Languages whose word count is character-based; also which we leave flagged for the
# on-demand translator. EPUB import text is the reader text, so is_raw stays False.
_CJK = ("zh", "ja", "ko")


def _assign_global_numbers(included: list[dict], offset: float) -> None:
    """Assign each included segment a strictly-increasing global ``_global`` number.
    Chapters keep their parsed number (+offset); non-chapter sections are slotted into the
    gaps (leading frontmatter just above the offset, trailing matter just after the prior
    chapter) so the reader's ``ORDER BY number`` lays them out correctly."""
    last = None
    for s in included:
        num = s.get("number")
        if num is not None:
            g = float(num) + offset
            if last is not None and g <= last:
                g = round(last + 0.001, 4)
        else:
            base = last if last is not None else offset
            g = round(base + 0.001, 4)
        s["_global"] = g
        last = g


async def _resolve_target(conn, job: dict, meta: dict):
    """Create-or-pick the target novel + source for this import. Three modes, keyed off
    ``options.target``:

      * ``"new"`` (or missing) — make a new novel (autofilled from meta) + a fresh source.
      * ``{"novel_id", "offset"}`` — append to an existing novel as an additional source.
      * ``{"source_id", "offset"?}`` — *replace* an existing source's chapters: its old
        chapters are deleted (chunks cascade), the source is re-pointed at this file, and the
        affected chapter range is returned so the codex over it can be invalidated.

    Returns ``(novel_id, source_dict, offset, cover_pending, invalidate_range)`` where
    ``invalidate_range`` is ``(lo, hi)`` of the replaced source's old chapters, else ``None``."""
    options = job.get("options") or {}
    target = options.get("target", "new")
    language = (meta.get("language") or "en")[:8]
    fmt = job["format"]
    # OCR'd CJK scans are stored as a raw source (text == source language) so the reader's
    # translation pipeline kicks in; EPUB/digital PDF are read as-is (is_raw stays False).
    is_raw = bool(options.get("is_raw"))

    # ── Replace an existing source's chapters ──
    if isinstance(target, dict) and target.get("source_id"):
        sid = int(target["source_id"])
        src_row = await conn.fetchrow(
            "SELECT id, novel_id, chapter_offset FROM sources WHERE id = $1;", sid)
        if not src_row:
            raise ValueError(f"Replace target source {sid} does not exist.")
        novel_id = int(src_row["novel_id"])
        offset = float(target.get("offset", src_row["chapter_offset"]) or 0)
        old = await conn.fetchrow(
            "SELECT MIN(number) AS lo, MAX(number) AS hi FROM chapters WHERE source_id = $1;", sid)
        # Drop the old chapters first (chunks FK-cascade) so the collision guard and the new
        # writes see a clean slate for this source.
        await conn.execute("DELETE FROM chapters WHERE source_id = $1;", sid)
        await conn.execute(
            """
            UPDATE sources SET adapter = $2, start_url = $3, language = $4, is_raw = $5,
                   chapter_offset = $6, label = $7 WHERE id = $1;
            """,
            sid, fmt, job["original_path"], language, is_raw, offset,
            f"Imported {fmt.upper()} (replaced)",
        )
        source = {"id": sid, "novel_id": novel_id, "is_raw": is_raw, "language": language}
        invalidate = (float(old["lo"]), float(old["hi"])) if old and old["lo"] is not None else None
        return novel_id, source, offset, None, invalidate

    # ── Append to an existing novel ──
    if isinstance(target, dict) and target.get("novel_id"):
        novel_id = int(target["novel_id"])
        offset = float(target.get("offset", 0) or 0)
        exists = await conn.fetchval("SELECT id FROM novels WHERE id = $1;", novel_id)
        if not exists:
            raise ValueError(f"Append target novel {novel_id} does not exist.")
        cover_pending = None
    # ── Brand-new novel ──
    else:
        # The uploader owns the imported novel; it starts private (they can publish it later).
        # Jobs created by CLI/tests/legacy code may not have a user; keep those readable as
        # system/global imports instead of creating an ownerless private orphan.
        owner_id = job.get("user_id")
        visibility = "private" if owner_id is not None else "global"
        novel_id = await conn.fetchval(
            """
            INSERT INTO novels (title, author, description, original_language, codex_enabled, series,
                                owner_id, visibility)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id;
            """,
            meta.get("title") or "Imported book", meta.get("author"),
            meta.get("description"), language, settings.IMPORT_AUTO_BUILD_CODEX,
            (meta.get("series") or None), owner_id, visibility,
        )
        novel_id = int(novel_id)
        offset = 0.0
        cover_pending = meta.get("cover_sha")
        # The owner sees their imported novel in their library immediately.
        if owner_id is not None:
            await conn.execute(
                "INSERT INTO library_entries (user_id, novel_id) VALUES ($1, $2) "
                "ON CONFLICT (user_id, novel_id) DO NOTHING;",
                owner_id, novel_id,
            )

    source_id = await conn.fetchval(
        """
        INSERT INTO sources (novel_id, adapter, start_url, config, language, is_raw, chapter_offset, label)
        VALUES ($1, $2, $3, '{}'::jsonb, $4, $5, $6, $7) RETURNING id;
        """,
        novel_id, fmt, job["original_path"], language, is_raw, offset,
        f"Imported {fmt.upper()}",
    )
    source = {"id": int(source_id), "novel_id": novel_id, "is_raw": is_raw, "language": language}
    return novel_id, source, offset, cover_pending, None


async def _commit_assets(conn, novel_id: int, job_id: int, shas: set[str], meta: dict) -> dict:
    """Promote every referenced staged image into the novel asset dir and return a
    sha → {url,width,height,mime} resolver map for the renderer."""
    assets_meta = meta.get("assets", {})
    resolver: dict[str, dict] = {}
    for sha in shas:
        am = assets_meta.get(sha)
        if not am:
            continue
        ext = am.get("ext", "bin")
        await storage.commit_asset(
            conn, novel_id, job_id, sha, ext,
            am.get("mime"), am.get("kind", "illustration"), am.get("width"), am.get("height"),
        )
        resolver[sha] = {
            "url": storage.asset_url(novel_id, sha, ext),
            "width": am.get("width"), "height": am.get("height"), "mime": am.get("mime"),
        }
    return resolver


async def _load_for_commit(job: dict) -> tuple:
    """Load the on-disk block stream + re-read the (possibly edited) plan/options/status from
    the row. Refuses an already-committed job (would duplicate the novel). Returns
    ``(document, included_segments)``; ``job['options']`` is refreshed in place."""
    job_id = int(job["id"])
    document = storage.load_blocks(job_id)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT plan, options, status, novel_id FROM import_jobs WHERE id = $1;", job_id)
    if row["status"] == "committed" and row["novel_id"] is not None:
        raise ValueError(
            f"Import job {job_id} was already committed to novel {int(row['novel_id'])}. "
            "Delete that novel or import again if you want a fresh copy.")
    plan = json.loads(row["plan"]) if isinstance(row["plan"], str) else (row["plan"] or {})
    if isinstance(row["options"], str):
        job["options"] = json.loads(row["options"])
    elif row["options"] is not None:
        job["options"] = row["options"]

    included = [s for s in plan.get("segments", []) if s.get("include")]
    included.sort(key=lambda s: s["block_range"][0])
    if not included:
        raise ValueError("Nothing to commit: no segments are marked include.")
    return document, included


async def _write_segments(conn, job_id: int, blocks: list, meta: dict, included: list[dict],
                          novel_id: int, source: dict, offset: float,
                          cover_pending: str | None, *, force_part_label: str | None = None,
                          sequential: bool = False) -> tuple[int, float, float]:
    """Render + persist every included segment into ``novel_id`` under ``source``. Shared by
    single-book commit, replace, and per-volume series commit. ``sequential`` ignores parsed
    numbers and lays the segments out as a contiguous run starting just after ``offset`` (used
    when stacking series volumes so a per-volume ``Chapter 1`` never collides). Returns
    ``(written, lo, hi)``."""
    from novelwiki.scraper.adapters import ChapterData
    from novelwiki.scraper.runner import _persist_chapter

    if sequential:
        for k, s in enumerate(included, start=1):
            s["_global"] = round(float(offset) + k, 4)
    else:
        _assign_global_numbers(included, offset)

    # Collision guard: never overwrite a chapter that belongs to a *different* source.
    existing = {
        float(r["number"])
        for r in await conn.fetch(
            "SELECT number FROM chapters WHERE novel_id = $1 AND source_id IS DISTINCT FROM $2;",
            novel_id, source["id"],
        )
    }
    clashes = sorted(s["_global"] for s in included if s["_global"] in existing)
    if clashes:
        raise ValueError(
            f"Import would collide with existing chapters at {clashes[:6]}"
            + ("…" if len(clashes) > 6 else "")
            + ". Adjust the append offset and retry.")

    ref_shas = {b.asset_sha for s in included
                for b in blocks[s["block_range"][0]:s["block_range"][1] + 1]
                if b.asset_sha}
    if cover_pending:
        ref_shas.add(cover_pending)
    resolver_map = await _commit_assets(conn, novel_id, job_id, ref_shas, meta)

    def resolver(sha):
        return resolver_map.get(sha)

    written = 0
    for s in included:
        seg_blocks = blocks[s["block_range"][0]:s["block_range"][1] + 1]
        raw_html, flat_text = render_segment(seg_blocks, resolver)
        ch = ChapterData(
            number=s["_global"], title=s.get("title") or f"Chapter {s['_global']}",
            content=flat_text, url=None, raw_html=raw_html,
        )
        await _persist_chapter(conn, source, s["_global"], ch, force=True)
        await conn.execute(
            "UPDATE chapters SET kind = $3, part_label = $4 WHERE novel_id = $1 AND number = $2;",
            novel_id, s["_global"], s.get("kind", "chapter"), force_part_label or s.get("part_label"),
        )
        written += 1

    # Autofill the cover from this book — but never clobber a cover already set (so a series'
    # later volumes don't overwrite the cover chosen from volume 1).
    if cover_pending and cover_pending in resolver_map:
        await conn.execute(
            "UPDATE novels SET cover_url = $2, updated_at = now() WHERE id = $1 AND cover_url IS NULL;",
            novel_id, resolver_map[cover_pending]["url"])

    lo = min(s["_global"] for s in included)
    hi = max(s["_global"] for s in included)
    return written, lo, hi


async def _finalize_job(conn, job_id: int, novel_id: int, source_id: int, stats: dict) -> None:
    """Record job completion INSIDE the caller's transaction so the novel, its chapters, the
    assets AND the 'committed' status all land atomically — a crash mid-commit rolls
    everything back (clean re-run) and a finished job is no longer a worker trigger state."""
    await conn.execute(
        """
        UPDATE import_jobs
        SET novel_id = $2, source_id = $3, status = 'committed', stage = 'committed',
            stats = $4::jsonb, error = NULL, updated_at = now()
        WHERE id = $1;
        """,
        job_id, novel_id, source_id, json.dumps(stats),
    )


async def _invalidate_codex_range(conn, novel_id: int, lo: float, hi: float) -> None:
    """After a source's chapters were replaced, drop the per-chapter codex artifacts over the
    affected range so a rebuild repopulates them. Chunks already vanished with the chapter
    delete (FK cascade); these tables key off the chapter number without an FK, so clear them
    by hand. Identity (entities/aliases/links) is left for the rebuild's extractor to reuse."""
    for table in ("extraction_state", "entity_facts", "relationships", "events", "entity_descriptions"):
        await conn.execute(
            f"DELETE FROM {table} WHERE novel_id = $1 AND chapter BETWEEN $2 AND $3;",
            novel_id, lo, hi)
    # Spoiler-ceiling caches are invalid once any content changed — cheap to drop wholesale.
    await conn.execute("DELETE FROM wiki_cache WHERE novel_id = $1;", novel_id)
    await conn.execute("DELETE FROM query_cache WHERE novel_id = $1;", novel_id)


async def commit_job(job: dict) -> dict:
    """Write the reviewed plan into chapters (new / append / replace). Returns
    {novel_id, source_id, stats}."""
    job_id = int(job["id"])
    document, included = await _load_for_commit(job)
    blocks, meta = document.blocks, document.meta

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            novel_id, source, offset, cover_pending, invalidate = await _resolve_target(conn, job, meta)
            written, lo, hi = await _write_segments(
                conn, job_id, blocks, meta, included, novel_id, source, offset, cover_pending)

            if invalidate is not None:
                # Replace: invalidate the codex over both the old and the new chapter spans.
                await _invalidate_codex_range(conn, novel_id, min(invalidate[0], lo), max(invalidate[1], hi))
            await conn.execute("UPDATE novels SET updated_at = now() WHERE id = $1;", novel_id)

            codex_enabled = await conn.fetchval("SELECT codex_enabled FROM novels WHERE id = $1;", novel_id)
            result_stats = {
                **(job.get("stats") or {}),
                "chapters_written": written, "from_chapter": lo, "to_chapter": hi,
            }
            await _finalize_job(conn, job_id, novel_id, source["id"], result_stats)

    if codex_enabled or settings.IMPORT_AUTO_BUILD_CODEX:
        _schedule_codex(novel_id, lo, hi)

    return {"novel_id": novel_id, "source_id": source["id"], "stats": result_stats}


def _series_index(meta: dict) -> float | None:
    v = meta.get("series_index")
    if v in (None, ""):
        return None
    try:
        return float(str(v).strip())
    except (ValueError, TypeError):
        return None


def _volume_label(idx: float | None, meta: dict) -> str:
    """The TOC group heading / source label for one volume of a series."""
    title = (meta.get("title") or "").strip()
    if title and title not in ("Imported book", "Imported PDF"):
        return title
    if idx is not None:
        return f"Volume {int(idx)}" if float(idx).is_integer() else f"Volume {idx}"
    return "Volume"


async def commit_series(job_ids: list[int]) -> dict:
    """Commit several parsed EPUB/PDF jobs as the volumes of ONE novel: ordered by detected
    series index, each volume becomes its own source, chapters are stacked into a single
    continuous global sequence, and every volume is grouped under its own ``part_label`` in
    the reader's TOC. The cover + book metadata come from the first volume."""
    from novelwiki.importer import jobs as jobs_mod

    loaded = []
    for jid in job_ids:
        job = await jobs_mod.get_job(int(jid))
        if not job:
            raise ValueError(f"Series job {jid} not found.")
        document, included = await _load_for_commit(job)
        loaded.append({"idx": _series_index(document.meta), "job": job,
                       "doc": document, "included": included})
    if not loaded:
        raise ValueError("commit_series called with no jobs.")
    # Order by series index (unknown indices sort last, then by job id for stability).
    loaded.sort(key=lambda t: (t["idx"] if t["idx"] is not None else float("inf"), int(t["job"]["id"])))

    first_meta = loaded[0]["doc"].meta
    language = (first_meta.get("language") or "en")[:8]
    series_name = first_meta.get("series") or first_meta.get("title") or "Imported series"
    owner_id = loaded[0]["job"].get("user_id")
    visibility = "private" if owner_id is not None else "global"

    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            novel_id = int(await conn.fetchval(
                """
                INSERT INTO novels (title, author, description, original_language, codex_enabled, series,
                                    owner_id, visibility)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING id;
                """,
                series_name, first_meta.get("author"), first_meta.get("description"),
                language, settings.IMPORT_AUTO_BUILD_CODEX, series_name, owner_id, visibility,
            ))
            if owner_id is not None:
                await conn.execute(
                    "INSERT INTO library_entries (user_id, novel_id) VALUES ($1, $2) "
                    "ON CONFLICT (user_id, novel_id) DO NOTHING;",
                    owner_id, novel_id,
                )
            running = 0.0
            lo_all = hi_all = None
            for i, item in enumerate(loaded):
                job, document, included = item["job"], item["doc"], item["included"]
                meta = document.meta
                is_raw = bool((job.get("options") or {}).get("is_raw"))
                fmt = job["format"]
                label = _volume_label(item["idx"], meta)
                source_id = int(await conn.fetchval(
                    """
                    INSERT INTO sources (novel_id, adapter, start_url, config, language, is_raw, chapter_offset, label)
                    VALUES ($1, $2, $3, '{}'::jsonb, $4, $5, $6, $7) RETURNING id;
                    """,
                    novel_id, fmt, job["original_path"], language, is_raw, running, label,
                ))
                source = {"id": source_id, "novel_id": novel_id, "is_raw": is_raw, "language": language}
                cover = meta.get("cover_sha") if i == 0 else None
                written, lo, hi = await _write_segments(
                    conn, int(job["id"]), document.blocks, meta, included, novel_id, source,
                    running, cover, force_part_label=label, sequential=True)
                running = hi  # the next volume stacks straight after this volume's last chapter
                lo_all = lo if lo_all is None else min(lo_all, lo)
                hi_all = hi if hi_all is None else max(hi_all, hi)
                await _finalize_job(conn, int(job["id"]), novel_id, source_id, {
                    **(job.get("stats") or {}),
                    "chapters_written": written, "from_chapter": lo, "to_chapter": hi,
                    "series": series_name,
                })
            codex_enabled = await conn.fetchval("SELECT codex_enabled FROM novels WHERE id = $1;", novel_id)

    if codex_enabled or settings.IMPORT_AUTO_BUILD_CODEX:
        _schedule_codex(novel_id, lo_all, hi_all)

    logger.info(f"Committed series '{series_name}' → novel {novel_id} ({len(loaded)} volumes, "
                f"ch. {lo_all}–{hi_all}).")
    return {"novel_id": novel_id, "volumes": len(loaded),
            "stats": {"from_chapter": lo_all, "to_chapter": hi_all, "series": series_name}}


def _schedule_codex(novel_id: int, frm: float, to: float) -> None:
    """Kick the codex pipeline over the imported range in the background (numbering is
    already final, so a later offset change won't be blocked)."""
    async def _run():
        try:
            from novelwiki.ingest.chunk import chunk_all_chapters
            from novelwiki.ingest.embed import embed_missing_chunks
            from novelwiki.ingest.extract import extract_all_chapters
            from novelwiki.retrieval.bm25 import get_bm25_manager
            await chunk_all_chapters(novel_id, force=False, from_chapter=frm, to_chapter=to)
            await embed_missing_chunks(novel_id, from_chapter=frm, to_chapter=to)
            await extract_all_chapters(novel_id, force=False, from_chapter=frm, to_chapter=to)
            await get_bm25_manager(novel_id).rebuild()
            logger.info(f"Codex built over imported chapters {frm}–{to} of novel {novel_id}.")
        except Exception as e:
            logger.warning(f"Background codex build for novel {novel_id} failed: {e}")
    try:
        asyncio.get_running_loop().create_task(_run())
    except RuntimeError:
        pass  # no loop (e.g. CLI) — caller can build the codex explicitly
