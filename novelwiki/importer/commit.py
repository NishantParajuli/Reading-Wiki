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
    """Create-or-pick the target novel + a fresh 'epub'/'pdf' source for this import.
    Returns (novel_id, source_dict, offset, cover_pending)."""
    options = job.get("options") or {}
    target = options.get("target", "new")
    language = (meta.get("language") or "en")[:8]
    fmt = job["format"]
    # OCR'd CJK scans are stored as a raw source (text == source language) so the reader's
    # translation pipeline kicks in; EPUB/digital PDF are read as-is (is_raw stays False).
    is_raw = bool(options.get("is_raw"))

    if isinstance(target, dict) and target.get("novel_id"):
        novel_id = int(target["novel_id"])
        offset = float(target.get("offset", 0) or 0)
        exists = await conn.fetchval("SELECT id FROM novels WHERE id = $1;", novel_id)
        if not exists:
            raise ValueError(f"Append target novel {novel_id} does not exist.")
        cover_pending = None
    else:
        novel_id = await conn.fetchval(
            """
            INSERT INTO novels (title, author, description, original_language, codex_enabled)
            VALUES ($1, $2, $3, $4, $5) RETURNING id;
            """,
            meta.get("title") or "Imported book", meta.get("author"),
            meta.get("description"), language, settings.IMPORT_AUTO_BUILD_CODEX,
        )
        novel_id = int(novel_id)
        offset = 0.0
        cover_pending = meta.get("cover_sha")

    source_id = await conn.fetchval(
        """
        INSERT INTO sources (novel_id, adapter, start_url, config, language, is_raw, chapter_offset, label)
        VALUES ($1, $2, $3, '{}'::jsonb, $4, $5, $6, $7) RETURNING id;
        """,
        novel_id, fmt, job["original_path"], language, is_raw, offset,
        f"Imported {fmt.upper()}",
    )
    source = {"id": int(source_id), "novel_id": novel_id, "is_raw": is_raw, "language": language}
    return novel_id, source, offset, cover_pending


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


async def commit_job(job: dict) -> dict:
    """Write the reviewed plan into chapters. Returns {novel_id, source_id, stats}."""
    job_id = int(job["id"])
    document = storage.load_blocks(job_id)
    blocks = document.blocks
    meta = document.meta

    # Re-read the (possibly user-edited) plan + options straight from the row.
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT plan, options FROM import_jobs WHERE id = $1;", job_id)
    import json as _json
    plan = _json.loads(row["plan"]) if isinstance(row["plan"], str) else (row["plan"] or {})
    if isinstance(row["options"], str):
        job["options"] = _json.loads(row["options"])
    elif row["options"] is not None:
        job["options"] = row["options"]

    included = [s for s in plan.get("segments", []) if s.get("include")]
    included.sort(key=lambda s: s["block_range"][0])
    if not included:
        raise ValueError("Nothing to commit: no segments are marked include.")

    from novelwiki.scraper.adapters import ChapterData
    from novelwiki.scraper.runner import _persist_chapter

    async with pool.acquire() as conn:
        async with conn.transaction():
            novel_id, source, offset, cover_pending = await _resolve_target(conn, job, meta)
            _assign_global_numbers(included, offset)

            # Collision guard: never overwrite a chapter that belongs to another source.
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
                    + ". Adjust the append offset and retry."
                )

            # Promote all referenced images (incl. the cover) before rendering.
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
                    novel_id, s["_global"], s.get("kind", "chapter"), s.get("part_label"),
                )
                written += 1

            # Autofill the new novel's cover from the EPUB once novel_id (and the file) exist.
            if cover_pending and cover_pending in resolver_map:
                await conn.execute(
                    "UPDATE novels SET cover_url = $2, updated_at = now() WHERE id = $1;",
                    novel_id, resolver_map[cover_pending]["url"],
                )
            else:
                await conn.execute("UPDATE novels SET updated_at = now() WHERE id = $1;", novel_id)

            codex_enabled = await conn.fetchval("SELECT codex_enabled FROM novels WHERE id = $1;", novel_id)

    lo = min(s["_global"] for s in included)
    hi = max(s["_global"] for s in included)
    if codex_enabled or settings.IMPORT_AUTO_BUILD_CODEX:
        _schedule_codex(novel_id, lo, hi)

    return {
        "novel_id": novel_id,
        "source_id": source["id"],
        "stats": {"chapters_written": written, "from_chapter": lo, "to_chapter": hi},
    }


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
