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

import json
import logging
import math

from novelwiki.platform.config import settings
from novelwiki.platform.database import get_db_pool
from novelwiki.modules.acquisition.adapters.outbound.importer import storage
from novelwiki.modules.acquisition.application.render import render_segment

logger = logging.getLogger(__name__)

# Languages whose word count is character-based; also which we leave flagged for the
# on-demand translator. EPUB import text is the reader text, so is_raw stays False.
_CJK = ("zh", "ja", "ko")
_METADATA_OVERRIDE_FIELDS = {
    "title", "author", "description", "language", "series",
    "series_index", "volume_label",
}


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


async def _resolve_target(apis, job: dict, meta: dict):
    options = job.get("options") or {}
    target = options.get("target", "new")
    as_volume = bool(options.get("as_volume"))
    language = (meta.get("language") or "en")[:8]
    fmt = job["format"]
    is_raw = bool(options.get("is_raw"))

    if isinstance(target, dict) and target.get("source_id"):
        source_id = int(target["source_id"])
        source_row = await apis.acquisition.import_source(source_id)
        if not source_row:
            raise ValueError(f"Replace target source {source_id} does not exist.")
        novel_id = int(source_row["novel_id"])
        offset = float(target.get("offset", source_row["chapter_offset"]) or 0)
        old_versions = await apis.reading.source_versions(source_id)
        if old_versions:
            await apis.reading.mark_overlay_conflicts(
                novel_id, tuple(old_versions)
            )
        await apis.reading.delete_source_chapters(source_id)
        await apis.acquisition.replace_import_source(
            source_id, adapter=fmt, start_url=job["original_path"],
            language=language, is_raw=is_raw, offset=offset,
            label=f"Imported {fmt.upper()} (replaced)",
        )
        source = {
            "id": source_id, "novel_id": novel_id, "is_raw": is_raw,
            "language": language, "old_versions": old_versions,
        }
        invalidate = (
            (min(old_versions), max(old_versions)) if old_versions else None
        )
        return novel_id, source, offset, None, invalidate

    if isinstance(target, dict) and target.get("novel_id"):
        novel_id = int(target["novel_id"])
        if not await apis.catalog.novel_exists(novel_id):
            raise ValueError(f"Append target novel {novel_id} does not exist.")
        if as_volume:
            existing = await apis.reading.other_source_numbers(novel_id, -1)
            offset = float(math.floor(max(existing))) if existing else 0.0
        else:
            offset = float(target.get("offset", 0) or 0)
        cover_pending = None
    else:
        from novelwiki.modules.acquisition.public import ImportNovelDraft
        owner_id = job.get("user_id")
        novel_id = await apis.catalog.create_imported_novel(ImportNovelDraft(
            title=(
                meta.get("series")
                if as_volume and meta.get("series")
                else meta.get("title")
            ) or "Imported book",
            author=meta.get("author"), description=meta.get("description"),
            original_language=language,
            codex_enabled=settings.IMPORT_AUTO_BUILD_CODEX,
            series=meta.get("series") or None, owner_id=owner_id,
            visibility="private" if owner_id is not None else "global",
        ))
        offset = 0.0
        cover_pending = meta.get("cover_sha")

    source_label = (
        _volume_label(_series_index(meta), meta)
        if as_volume
        else f"Imported {fmt.upper()}"
    )
    source_id = await apis.acquisition.create_import_source(
        novel_id, adapter=fmt, start_url=job["original_path"],
        language=language, is_raw=is_raw, offset=offset,
        label=source_label,
    )
    source = {
        "id": source_id, "novel_id": novel_id,
        "is_raw": is_raw, "language": language,
    }
    return novel_id, source, offset, cover_pending, None


async def _commit_assets(acquisition, novel_id: int, job_id: int, shas: set[str], meta: dict) -> dict:
    """Promote every referenced staged image into the novel asset dir and return a
    sha → {url,width,height,mime} resolver map for the renderer."""
    assets_meta = meta.get("assets", {})
    resolver: dict[str, dict] = {}
    for sha in shas:
        am = assets_meta.get(sha)
        if not am:
            continue
        ext = am.get("ext", "bin")
        resolver[sha] = await acquisition.commit_import_asset(
            novel_id, job_id, sha, ext, am.get("mime"),
            am.get("kind", "illustration"), am.get("width"), am.get("height"),
        )
    return resolver


async def _preserve_replaced_content_version(
    reading, novel_id: int, number: float, source: dict
) -> int | None:
    """Compatibility seam retained for the pre-migration regression fixture."""
    previous = (source.get("old_versions") or {}).get(float(number))
    if previous is None:
        return None
    return await reading.preserve_content_version(
        novel_id, number, int(previous) + 1
    )


def _apply_metadata_override(document, options: dict) -> None:
    """Apply the user's saved review values to the parsed document.

    The on-disk block stream deliberately remains immutable after parsing. Overrides live
    on the durable job row, so this step is required for both ordinary and series commits.
    Restricting the keys keeps clients from replacing parser-owned asset/cover metadata.
    """
    override = options.get("metadata_override") or {}
    if not isinstance(override, dict):
        return
    for key in _METADATA_OVERRIDE_FIELDS:
        if key in override:
            document.meta[key] = override[key]


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
    _apply_metadata_override(document, job.get("options") or {})

    included = [s for s in plan.get("segments", []) if s.get("include")]
    included.sort(key=lambda s: s["block_range"][0])
    if not included:
        raise ValueError("Nothing to commit: no segments are marked include.")
    return document, included


async def _write_segments(apis, job_id: int, blocks: list, meta: dict,
                          included: list[dict], novel_id: int, source: dict,
                          offset: float, cover_pending: str | None, *,
                          force_part_label: str | None = None,
                          sequential: bool = False) -> tuple[int, float, float]:
    from novelwiki.modules.acquisition.adapters.outbound.scraper.adapters import ChapterData

    if sequential:
        for index, segment in enumerate(included, start=1):
            segment["_global"] = round(float(offset) + index, 4)
    else:
        _assign_global_numbers(included, offset)

    existing = await apis.reading.other_source_numbers(novel_id, source["id"])
    clashes = sorted(
        segment["_global"] for segment in included
        if segment["_global"] in existing
    )
    if clashes:
        raise ValueError(
            f"Import would collide with existing chapters at {clashes[:6]}"
            + ("…" if len(clashes) > 6 else "")
            + ". Adjust the append offset and retry."
        )

    ref_shas = {
        block.asset_sha
        for segment in included
        for block in blocks[
            segment["block_range"][0]:segment["block_range"][1] + 1
        ]
        if block.asset_sha
    }
    if cover_pending:
        ref_shas.add(cover_pending)
    resolver_map = await _commit_assets(
        apis.acquisition, novel_id, job_id, ref_shas, meta
    )

    written = 0
    old_versions = source.get("old_versions") or {}
    for segment in included:
        raw_html, flat_text = render_segment(
            blocks[segment["block_range"][0]:segment["block_range"][1] + 1],
            resolver_map.get,
        )
        chapter = ChapterData(
            number=segment["_global"],
            title=segment.get("title") or f"Chapter {segment['_global']}",
            content=flat_text, url=None, raw_html=raw_html,
        )
        previous = old_versions.get(float(segment["_global"]))
        await apis.reading.upsert_ingested_chapter(
            source, segment["_global"], chapter, True,
            kind=segment.get("kind", "chapter"),
            part_label=force_part_label or segment.get("part_label"),
            minimum_content_version=(int(previous) + 1 if previous is not None else None),
        )
        written += 1

    if cover_pending and cover_pending in resolver_map:
        await apis.catalog.set_cover_if_missing(
            novel_id, resolver_map[cover_pending]["url"]
        )
    return (
        written,
        min(segment["_global"] for segment in included),
        max(segment["_global"] for segment in included),
    )


async def commit_job(job: dict, *, runtime) -> dict:
    """Write the reviewed plan into chapters (new / append / replace). Returns
    {novel_id, source_id, stats}."""
    job_id = int(job["id"])
    document, included = await _load_for_commit(job)
    blocks, meta = document.blocks, document.meta

    from novelwiki.workflows.commit_import import commit_import

    state = {}

    async def operation(apis):
        novel_id, source, offset, cover_pending, invalidate = await _resolve_target(
            apis, job, meta
        )
        options = job.get("options") or {}
        target = options.get("target")
        as_volume = bool(options.get("as_volume"))
        volume_commit = (
            as_volume
            and not (
                isinstance(target, dict)
                and bool(target.get("source_id"))
            )
        )
        written, lo, hi = await _write_segments(
            apis, job_id, blocks, meta, included, novel_id, source, offset,
            cover_pending,
            force_part_label=(
                _volume_label(_series_index(meta), meta) if volume_commit else None
            ),
            sequential=volume_commit,
        )
        if invalidate is not None:
            await apis.codex.invalidate_chapter_range(
                novel_id, min(invalidate[0], lo), max(invalidate[1], hi)
            )
        await apis.catalog.touch_novel(novel_id)
        result_stats = {
            **(job.get("stats") or {}), "chapters_written": written,
            "from_chapter": lo, "to_chapter": hi,
        }
        await apis.acquisition.finalize_import_job(
            job_id, novel_id, source["id"], result_stats
        )
        state.update(
            novel_id=novel_id, source_id=source["id"], lo=lo, hi=hi,
            codex_enabled=await apis.catalog.codex_enabled(novel_id),
            stats=result_stats,
        )
        return state

    await commit_import(await runtime.commit_uow_factory(), operation)
    novel_id, lo, hi = state["novel_id"], state["lo"], state["hi"]
    codex_enabled, result_stats = state["codex_enabled"], state["stats"]

    if codex_enabled or settings.IMPORT_AUTO_BUILD_CODEX:
        if await _reserve_auto_codex(job.get("user_id"), runtime=runtime):
            await _schedule_codex(
                novel_id, lo, hi, job.get("user_id"), runtime=runtime
            )
        else:
            logger.info(f"Skipped automatic codex build for imported novel {novel_id}: owner is not quota-eligible.")

    return {"novel_id": novel_id, "source_id": state["source_id"], "stats": result_stats}


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
    explicit = (meta.get("volume_label") or "").strip()
    if explicit:
        return explicit
    title = (meta.get("title") or "").strip()
    if title and title not in ("Imported book", "Imported PDF"):
        return title
    if idx is not None:
        return f"Volume {int(idx)}" if float(idx).is_integer() else f"Volume {idx}"
    return "Volume"


async def commit_series(
    job_ids: list[int], target_novel_id: int | None = None, *, runtime
) -> dict:
    """Commit several parsed EPUB/PDF jobs as the volumes of ONE novel: ordered by detected
    series index, each volume becomes its own source, chapters are stacked into a single
    continuous global sequence, and every volume is grouped under its own ``part_label`` in
    the reader's TOC. With ``target_novel_id`` the volumes append after that novel's current
    final chapter; otherwise a new novel is created. The first volume supplies missing cover
    + book metadata for a new novel."""
    loaded = []
    for jid in job_ids:
        job = await runtime.import_job(int(jid))
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

    from novelwiki.modules.acquisition.public import ImportNovelDraft
    from novelwiki.workflows.commit_import import commit_import

    state = {}

    async def operation(apis):
        if target_novel_id is not None:
            novel_id = int(target_novel_id)
            if not await apis.catalog.novel_exists(novel_id):
                raise ValueError(f"Append target novel {novel_id} does not exist.")
            existing = await apis.reading.other_source_numbers(novel_id, -1)
            running = float(math.floor(max(existing))) if existing else 0.0
        else:
            novel_id = await apis.catalog.create_imported_novel(ImportNovelDraft(
                title=series_name, author=first_meta.get("author"),
                description=first_meta.get("description"), original_language=language,
                codex_enabled=settings.IMPORT_AUTO_BUILD_CODEX, series=series_name,
                owner_id=owner_id, visibility=visibility,
            ))
            running = 0.0
        lo_all = hi_all = None
        for index, item in enumerate(loaded):
            job, document, included = item["job"], item["doc"], item["included"]
            meta = document.meta
            is_raw = bool((job.get("options") or {}).get("is_raw"))
            label = _volume_label(item["idx"], meta)
            source_id = await apis.acquisition.create_import_source(
                novel_id, adapter=job["format"], start_url=job["original_path"],
                language=language, is_raw=is_raw, offset=running, label=label,
            )
            source = {"id": source_id, "novel_id": novel_id,
                      "is_raw": is_raw, "language": language}
            written, lo, hi = await _write_segments(
                apis, int(job["id"]), document.blocks, meta, included, novel_id,
                source, running, meta.get("cover_sha") if index == 0 else None,
                force_part_label=label, sequential=True,
            )
            running = hi
            lo_all = lo if lo_all is None else min(lo_all, lo)
            hi_all = hi if hi_all is None else max(hi_all, hi)
            await apis.acquisition.finalize_import_job(
                int(job["id"]), novel_id, source_id, {
                    **(job.get("stats") or {}), "chapters_written": written,
                    "from_chapter": lo, "to_chapter": hi, "series": series_name,
                },
            )
        await apis.catalog.touch_novel(novel_id)
        state.update(
            novel_id=novel_id, lo=lo_all, hi=hi_all,
            codex_enabled=await apis.catalog.codex_enabled(novel_id),
        )
        return state

    await commit_import(await runtime.commit_uow_factory(), operation)
    novel_id, lo_all, hi_all = state["novel_id"], state["lo"], state["hi"]
    codex_enabled = state["codex_enabled"]

    if codex_enabled or settings.IMPORT_AUTO_BUILD_CODEX:
        if await _reserve_auto_codex(owner_id, runtime=runtime):
            await _schedule_codex(
                novel_id, lo_all, hi_all, owner_id, runtime=runtime
            )
        else:
            logger.info(f"Skipped automatic codex build for imported series {novel_id}: owner is not quota-eligible.")

    logger.info(f"Committed series '{series_name}' → novel {novel_id} ({len(loaded)} volumes, "
                f"ch. {lo_all}–{hi_all}).")
    return {"novel_id": novel_id, "volumes": len(loaded),
            "appended": target_novel_id is not None,
            "stats": {"from_chapter": lo_all, "to_chapter": hi_all, "series": series_name}}


async def _reserve_auto_codex(user_id: int | None, *, runtime) -> bool:
    """Reserve the codex quota for import-triggered background builds. Trusted CLI/system
    imports (no user_id) keep the old behavior; user-owned imports must be verified and
    under quota before the build is scheduled."""
    if user_id is None:
        return True
    return await runtime.reserve_auto_codex(user_id)


async def _schedule_codex(
    novel_id: int, frm: float, to: float, user_id: int | None, *, runtime
) -> None:
    """Enqueue a DURABLE codex build over the imported range (numbering is already final, so a
    later offset change won't be blocked). Replaces the old fire-and-forget task: the codex-build
    quota reserved by ``_reserve_auto_codex`` is now recorded on the job and refunded by the worker
    if the build fails, and the work survives a restart instead of being silently lost."""
    try:
        await runtime.schedule_codex(novel_id, frm, to, user_id)
        logger.info(f"Scheduled durable codex build over imported chapters {frm}–{to} of novel {novel_id}.")
    except Exception as e:
        logger.warning(f"Could not schedule codex build for novel {novel_id}: {e}")
