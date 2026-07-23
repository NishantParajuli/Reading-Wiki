"""Tests for the S4 import features: quality score, resumable chunked upload, series
grouping, replace-source, and re-import-by-hash detection.

The pure-logic tests (quality, chunked-upload storage IO) need no DB; the commit-path tests
(series / replace / hash) hit Postgres and skip when none is reachable.
"""
import io
import os
import zipfile

import pytest
import pytest_asyncio

from novelwiki.importer import cleanup, segment, storage, quality
from novelwiki.importer.parsers import epub as epub_parser
from novelwiki.eval.import_tests import _png


# ── Fixture EPUB builder (parametric: title / series / index / chapter count) ─

def make_series_epub(path: str, *, title: str, series: str, index, chapters: int = 2):
    opf_items, spine, files = [], [], {}
    opf_items.append('<item id="cover-img" href="cover.png" media-type="image/png" properties="cover-image"/>')
    for i in range(1, chapters + 1):
        opf_items.append(f'<item id="chap{i}" href="chap{i}.xhtml" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="chap{i}"/>')
        files[f"OEBPS/chap{i}.xhtml"] = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<html xmlns="http://www.w3.org/1999/xhtml"><body>'
            f'<h1>Chapter {i}</h1><p>Body text for chapter {i} of {title}. '
            'It has enough words to count as real prose for the quality score.</p>'
            '</body></html>'
        )
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:title>{title}</dc:title><dc:creator>Ada Mariner</dc:creator><dc:language>en</dc:language>'
        f'<meta name="calibre:series" content="{series}"/>'
        f'<meta name="calibre:series_index" content="{index}"/>'
        '<meta name="cover" content="cover-img"/>'
        '</metadata>'
        f'<manifest>{"".join(opf_items)}</manifest>'
        f'<spine>{"".join(spine)}</spine></package>'
    )
    container = (
        '<?xml version="1.0"?>'
        '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>'
        '</container>'
    )
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", container)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/cover.png", _png(4, 6))
        for name, body in files.items():
            z.writestr(name, body)


# ── Pure tests ───────────────────────────────────────────────────────────────

def test_quality_score(tmp_path):
    path = str(tmp_path / "q.epub")
    make_series_epub(path, title="Quality Probe", series="QS", index=1, chapters=3)
    job_id = 991001
    try:
        doc = epub_parser.parse_epub(path, job_id)
        cleanup.clean_document(doc)
        plan = segment.build_plan(doc)
        q = quality.compute_quality(doc, plan)
        assert 0 <= q["score"] <= 100
        assert q["score"] >= 60                       # a clean 3-chapter book should score well
        labels = {f["label"]: f for f in q["factors"]}
        assert labels["Chapters"]["ok"] is True
        assert labels["Metadata"]["ok"] is True       # title detected
        assert labels["Encoding"]["ok"] is True
    finally:
        storage.cleanup_job(job_id)


def test_quality_flags_empty_document():
    from novelwiki.importer.ir import Document
    doc = Document(blocks=[], meta={"title": "Imported book"}, format="epub")
    q = quality.compute_quality(doc, {"segments": []})
    assert q["score"] < 50                            # no title, no chapters, no prose
    assert any(f["label"] == "Chapters" and not f["ok"] for f in q["factors"])


def test_chunked_upload_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(storage.settings, "IMPORT_DIR", str(tmp_path / "imports"))
    job_id = 991002
    payload = os.urandom(5000)
    storage.init_upload(job_id, "epub")
    assert storage.upload_offset(job_id, "epub") == 0
    # Upload in three contiguous chunks.
    off = 0
    for chunk in (payload[:2000], payload[2000:4500], payload[4500:]):
        off = storage.write_chunk(job_id, "epub", off, chunk)
    assert off == len(payload)
    assert storage.upload_offset(job_id, "epub") == len(payload)
    sha, size = storage.finalize_upload(job_id, "epub")
    assert size == len(payload)
    assert sha == storage.sha256_bytes(payload)
    storage.cleanup_job(job_id)


# ── DB-backed commit tests ───────────────────────────────────────────────────

@pytest_asyncio.fixture()
async def db_ready():
    import asyncio
    import asyncpg
    from novelwiki.config.settings import settings
    try:
        conn = await asyncio.wait_for(asyncpg.connect(settings.DATABASE_URL), timeout=3)
        await conn.close()
    except Exception:
        pytest.skip("No Postgres reachable; skipping S4 commit integration tests.")
    from novelwiki.db.schema import init_database
    await init_database()
    yield
    from novelwiki.db.connection import close_db_pool
    await close_db_pool()


async def _parse_job(path: str, fmt: str = "epub") -> int:
    from novelwiki.importer import jobs as import_jobs
    job_id = await import_jobs.create_job(fmt, os.path.abspath(path), status="receiving")
    doc = epub_parser.parse_epub(path, job_id)
    cleanup.clean_document(doc)
    storage.save_blocks(job_id, doc)
    plan = segment.build_plan(doc)
    await import_jobs.update_job(
        job_id, plan=plan, status="awaiting_review",
        detected_meta={"title": doc.meta.get("title"), "series": doc.meta.get("series"),
                       "series_index": doc.meta.get("series_index")})
    return job_id


@pytest.mark.asyncio
async def test_series_commit_end_to_end(tmp_path, db_ready):
    from novelwiki.importer import commit
    from novelwiki.db.connection import get_db_pool

    v1 = str(tmp_path / "v1.epub"); v2 = str(tmp_path / "v2.epub")
    make_series_epub(v1, title="Saga Vol One", series="The Saga", index=1, chapters=2)
    make_series_epub(v2, title="Saga Vol Two", series="The Saga", index=2, chapters=2)
    # Deliberately parse vol 2 first to prove ordering is by series index, not job order.
    jid2 = await _parse_job(v2)
    jid1 = await _parse_job(v1)

    novel_id = None
    try:
        res = await commit.commit_series([jid2, jid1])
        novel_id = res["novel_id"]
        assert res["volumes"] == 2
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT number, part_label, source_id FROM chapters WHERE novel_id=$1 ORDER BY number;", novel_id)
            assert [float(r["number"]) for r in rows] == [1.0, 2.0, 3.0, 4.0]  # stacked, no collision
            # First two chapters belong to vol 1, last two to vol 2 (distinct sources + labels).
            assert rows[0]["part_label"] == "Saga Vol One"
            assert rows[3]["part_label"] == "Saga Vol Two"
            assert rows[0]["source_id"] != rows[3]["source_id"]
            n_sources = await conn.fetchval("SELECT COUNT(*) FROM sources WHERE novel_id=$1;", novel_id)
            assert n_sources == 2
            series = await conn.fetchval("SELECT series FROM novels WHERE id=$1;", novel_id)
            assert series == "The Saga"
    finally:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            if novel_id is not None:
                await conn.execute("DELETE FROM novels WHERE id=$1;", novel_id)
            await conn.execute("DELETE FROM import_jobs WHERE id = ANY($1::bigint[]);", [jid1, jid2])
        if novel_id is not None:
            storage.cleanup_novel_assets(novel_id)
        storage.cleanup_job(jid1); storage.cleanup_job(jid2)


@pytest.mark.asyncio
async def test_single_volume_auto_appends_and_groups(tmp_path, db_ready):
    from novelwiki.importer import commit, jobs as import_jobs
    from novelwiki.db.connection import get_db_pool

    v1 = str(tmp_path / "v1.epub"); v2 = str(tmp_path / "v2.epub")
    make_series_epub(v1, title="Saga Vol One", series="The Saga", index=1, chapters=2)
    make_series_epub(v2, title="Saga Vol Two", series="The Saga", index=2, chapters=2)
    jid1 = await _parse_job(v1)
    jid2 = await _parse_job(v2)
    novel_id = None
    try:
        await import_jobs.update_job(
            jid1, options={"target": "new", "as_volume": True},
        )
        first = await commit.commit_job(await import_jobs.get_job(jid1))
        novel_id = first["novel_id"]

        await import_jobs.update_job(
            jid2,
            options={
                "target": {"novel_id": novel_id, "offset": 0},
                "as_volume": True,
            },
        )
        second = await commit.commit_job(await import_jobs.get_job(jid2))
        assert second["novel_id"] == novel_id

        pool = await get_db_pool()
        async with pool.acquire() as conn:
            novel = await conn.fetchrow(
                "SELECT title, series FROM novels WHERE id=$1;", novel_id,
            )
            rows = await conn.fetch(
                "SELECT number, part_label FROM chapters "
                "WHERE novel_id=$1 ORDER BY number;", novel_id,
            )
            sources = await conn.fetch(
                "SELECT chapter_offset, label FROM sources "
                "WHERE novel_id=$1 ORDER BY id;", novel_id,
            )
        assert dict(novel) == {"title": "The Saga", "series": "The Saga"}
        assert [float(row["number"]) for row in rows] == [1.0, 2.0, 3.0, 4.0]
        assert [row["part_label"] for row in rows] == [
            "Saga Vol One", "Saga Vol One", "Saga Vol Two", "Saga Vol Two",
        ]
        assert [row["label"] for row in sources] == [
            "Saga Vol One", "Saga Vol Two",
        ]
        assert float(sources[1]["chapter_offset"]) == 2.0
    finally:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            if novel_id is not None:
                await conn.execute("DELETE FROM novels WHERE id=$1;", novel_id)
            await conn.execute(
                "DELETE FROM import_jobs WHERE id = ANY($1::bigint[]);",
                [jid1, jid2],
            )
        if novel_id is not None:
            storage.cleanup_novel_assets(novel_id)
        storage.cleanup_job(jid1); storage.cleanup_job(jid2)


@pytest.mark.asyncio
async def test_series_batch_appends_to_existing_novel(tmp_path, db_ready):
    from novelwiki.importer import commit, jobs as import_jobs
    from novelwiki.db.connection import get_db_pool

    v1 = str(tmp_path / "v1.epub")
    v2 = str(tmp_path / "v2.epub")
    v3 = str(tmp_path / "v3.epub")
    make_series_epub(v1, title="Saga Vol One", series="The Saga", index=1, chapters=2)
    make_series_epub(v2, title="Saga Vol Two", series="The Saga", index=2, chapters=2)
    make_series_epub(v3, title="Saga Vol Three", series="The Saga", index=3, chapters=2)
    jid1 = await _parse_job(v1)
    jid2 = await _parse_job(v2)
    jid3 = await _parse_job(v3)
    novel_id = None
    try:
        initial = await commit.commit_series([jid1])
        novel_id = initial["novel_id"]
        appended = await commit.commit_series(
            [jid3, jid2], target_novel_id=novel_id,
        )
        assert appended["novel_id"] == novel_id
        assert appended["appended"] is True

        pool = await get_db_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT number, part_label FROM chapters "
                "WHERE novel_id=$1 ORDER BY number;", novel_id,
            )
        assert [float(row["number"]) for row in rows] == [
            1.0, 2.0, 3.0, 4.0, 5.0, 6.0,
        ]
        assert [row["part_label"] for row in rows] == [
            "Saga Vol One", "Saga Vol One",
            "Saga Vol Two", "Saga Vol Two",
            "Saga Vol Three", "Saga Vol Three",
        ]
    finally:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            if novel_id is not None:
                await conn.execute("DELETE FROM novels WHERE id=$1;", novel_id)
            await conn.execute(
                "DELETE FROM import_jobs WHERE id = ANY($1::bigint[]);",
                [jid1, jid2, jid3],
            )
        if novel_id is not None:
            storage.cleanup_novel_assets(novel_id)
        storage.cleanup_job(jid1); storage.cleanup_job(jid2); storage.cleanup_job(jid3)


@pytest.mark.asyncio
async def test_replace_source_end_to_end(tmp_path, db_ready):
    from novelwiki.importer import commit, jobs as import_jobs
    from novelwiki.db.connection import get_db_pool

    first = str(tmp_path / "first.epub"); repl = str(tmp_path / "repl.epub")
    make_series_epub(first, title="Replace Me", series="RS", index=1, chapters=2)
    make_series_epub(repl, title="Replace Me v2", series="RS", index=1, chapters=3)

    jid1 = await _parse_job(first)
    res1 = await commit.commit_job(await import_jobs.get_job(jid1))
    novel_id = res1["novel_id"]; source_id = res1["source_id"]

    jid2 = await _parse_job(repl)
    try:
        await import_jobs.update_job(jid2, options={"target": {"source_id": source_id}})
        res2 = await commit.commit_job(await import_jobs.get_job(jid2))
        assert res2["novel_id"] == novel_id
        assert res2["source_id"] == source_id
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            nums = [float(r["number"]) for r in await conn.fetch(
                "SELECT number FROM chapters WHERE novel_id=$1 ORDER BY number;", novel_id)]
            assert nums == [1.0, 2.0, 3.0]            # 3 fresh chapters replaced the old 2
            adapter, label = await conn.fetchrow(
                "SELECT adapter, label FROM sources WHERE id=$1;", source_id)
            assert adapter == "epub" and "replaced" in (label or "")
    finally:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM novels WHERE id=$1;", novel_id)
            await conn.execute("DELETE FROM import_jobs WHERE id = ANY($1::bigint[]);", [jid1, jid2])
        storage.cleanup_novel_assets(novel_id)
        storage.cleanup_job(jid1); storage.cleanup_job(jid2)


@pytest.mark.asyncio
async def test_reimport_hash_detection(tmp_path, db_ready):
    from novelwiki.importer import commit, jobs as import_jobs
    from novelwiki.db.connection import get_db_pool

    path = str(tmp_path / "dup.epub")
    make_series_epub(path, title="Dup Book", series="DS", index=1, chapters=2)
    sha = "deadbeef" + "0" * 56

    jid1 = await _parse_job(path)
    await import_jobs.update_job(jid1, file_sha256=sha)
    res = await commit.commit_job(await import_jobs.get_job(jid1))
    novel_id = res["novel_id"]

    jid2 = await import_jobs.create_job("epub", os.path.abspath(path), file_sha256=sha, status="uploaded")
    try:
        dups = await import_jobs.imports_with_hash(sha, exclude_job_id=jid2)
        ids = {d["job_id"] for d in dups}
        assert jid1 in ids and jid2 not in ids
        committed = [d for d in dups if d["job_id"] == jid1][0]
        assert committed["novel_id"] == novel_id
        assert committed["novel_title"] == "Dup Book"
    finally:
        pool = await get_db_pool()
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM novels WHERE id=$1;", novel_id)
            await conn.execute("DELETE FROM import_jobs WHERE id = ANY($1::bigint[]);", [jid1, jid2])
        storage.cleanup_novel_assets(novel_id)
        storage.cleanup_job(jid1); storage.cleanup_job(jid2)
