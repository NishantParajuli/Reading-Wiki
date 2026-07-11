"""Regression tests for Batch 9: product-operations + reader MVP.

Covers the trust/quota/spoiler invariants of the new surfaces:
  - the unified /home only ever surfaces novels the caller can read,
  - /discover filters select the right shared novels and exclude unreadable ones,
  - the no-spoiler recap clamps to the trusted effective ceiling and never feeds the model
    evidence above the reader's real progress (and cache hits stay free),
  - /cost-estimate reports units + remaining quota without charging,
  - the /health panel counts codex/translation/audio states correctly, and
  - the /activity feed is scoped to the caller's own jobs.
"""
import pytest
import pytest_asyncio

import novelwiki.db.connection as db_connection
from novelwiki import ai_limits
from novelwiki.api import routes
from novelwiki.api import routes_product as prod
from novelwiki.api import routes_tts as tts_routes
from novelwiki.db.connection import close_db_pool, get_db_pool
from novelwiki.db.schema import init_database


async def _reset_pool():
    try:
        await close_db_pool()
    except RuntimeError:
        pass
    db_connection._pool = None


class _FakeBm25:
    async def ensure_loaded(self):
        return None


@pytest_asyncio.fixture()
async def db():
    await _reset_pool()
    await init_database()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            for t in ("query_cache", "ai_request_locks", "auth_rate_limits", "chapter_audio",
                      "jobs", "import_jobs", "tts_jobs", "chunks", "entities",
                      "reading_progress", "library_entries", "chapters", "sources", "novels", "users"):
                await conn.execute(f"DELETE FROM {t} CASCADE;")

        reader = await conn.fetchrow(
            "INSERT INTO users (email, username, display_name, role, email_verified) "
            "VALUES ('r@t.test', 'reader', 'Reader', 'user', TRUE) RETURNING *;")
        other = await conn.fetchrow(
            "INSERT INTO users (email, username, display_name, role, email_verified) "
            "VALUES ('o@t.test', 'other', 'Other', 'user', TRUE) RETURNING *;")

    yield {"pool": pool, "reader": dict(reader), "other": dict(other)}
    await _reset_pool()


async def _mk_novel(pool, *, owner_id, visibility="public", title="N", codex=False,
                    language="en", tags=None, chapters=3, raw=False, eng=True):
    async with pool.acquire() as conn:
        nid = await conn.fetchval(
            "INSERT INTO novels (title, owner_id, visibility, codex_enabled, original_language, status_tags) "
            "VALUES ($1, $2, $3, $4, $5, $6) RETURNING id;",
            title, owner_id, visibility, codex, language, tags or [])
        if raw or eng:
            await conn.execute(
                "INSERT INTO sources (novel_id, adapter, is_raw, language) VALUES ($1, $2, $3, $4);",
                nid, "fenrirealm", raw, language)
        for i in range(1, chapters + 1):
            await conn.execute(
                "INSERT INTO chapters (novel_id, number, title, content, original_text, "
                "is_translated, translation_status) VALUES ($1, $2, $3, $4, $5, $6, $7);",
                nid, i, f"Ch{i}",
                (None if raw and i == chapters else f"content {i}"),   # raw novels leave last ch untranslated
                (f"orig {i}" if raw else None),
                (raw and i < chapters),
                ("done" if (not raw or i < chapters) else "none"))
    return nid


async def _set_progress(pool, user_id, nid, last, maxread):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO reading_progress (user_id, novel_id, last_chapter, max_chapter_read, scroll_pct) "
            "VALUES ($1, $2, $3, $4, 0) ON CONFLICT (user_id, novel_id) DO UPDATE "
            "SET last_chapter = EXCLUDED.last_chapter, max_chapter_read = EXCLUDED.max_chapter_read;",
            user_id, nid, last, maxread)


async def _add_library(pool, user_id, nid):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO library_entries (user_id, novel_id) VALUES ($1, $2) ON CONFLICT DO NOTHING;",
            user_id, nid)


# ── Home only shows readable novels ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_home_continue_reading_excludes_unreadable(db):
    pool, reader, other = db["pool"], db["reader"], db["other"]
    public = await _mk_novel(pool, owner_id=other["id"], visibility="public", title="Public")
    owned = await _mk_novel(pool, owner_id=reader["id"], visibility="private", title="Owned")
    direct_public = await _mk_novel(pool, owner_id=other["id"], visibility="public", title="Direct")
    # A novel the reader once added, now flipped private by its owner — no longer readable.
    gone = await _mk_novel(pool, owner_id=other["id"], visibility="private", title="Gone")

    for nid in (public, owned, gone):
        await _add_library(pool, reader["id"], nid)
        await _set_progress(pool, reader["id"], nid, 2, 2)
    # Discover can open public/global novels before the user explicitly adds them.
    # Their progress is still readable and should appear on the Continue home.
    await _set_progress(pool, reader["id"], direct_public, 2, 2)

    home = await prod.api_home(user=reader)
    ids = {n["id"] for n in home["continue_reading"]}
    assert public in ids and owned in ids and direct_public in ids
    assert gone not in ids, "a now-private novel the reader doesn't own must not appear"


@pytest.mark.asyncio
async def test_home_continue_listening_needs_audio(db):
    pool, reader, other = db["pool"], db["reader"], db["other"]
    quiet = await _mk_novel(pool, owner_id=other["id"], title="Quiet")
    loud = await _mk_novel(pool, owner_id=other["id"], title="Loud")
    stale = await _mk_novel(pool, owner_id=other["id"], title="StaleAudio")
    for nid in (quiet, loud, stale):
        await _add_library(pool, reader["id"], nid)
        await _set_progress(pool, reader["id"], nid, 1, 1)
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO chapter_audio (novel_id, chapter, voice_id, audio_path, user_id) "
            "VALUES ($1, 1, 'v1', 'x.opus', NULL);", loud)
        await conn.execute("UPDATE chapters SET content_version = 2 WHERE novel_id = $1 AND number = 1;", stale)
        await conn.execute(
            "INSERT INTO chapter_audio (novel_id, chapter, voice_id, content_version, audio_path, user_id) "
            "VALUES ($1, 1, 'v1', 1, 'stale.opus', NULL);", stale)

    home = await prod.api_home(user=reader)
    listening = {n["id"] for n in home["continue_listening"]}
    assert loud in listening and quiet not in listening
    assert stale not in listening, "stale audio must not make a novel listenable"


# ── Discover filters ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_discover_filters(db):
    pool, reader, other = db["pool"], db["reader"], db["other"]
    en_codex = await _mk_novel(pool, owner_id=other["id"], title="EnCodex", codex=True, language="en")
    ja_raw = await _mk_novel(pool, owner_id=other["id"], title="JaRaw", language="ja", raw=True, eng=False)
    tagged = await _mk_novel(pool, owner_id=other["id"], title="Tagged", tags=["ongoing", "fantasy"])
    private_other = await _mk_novel(pool, owner_id=other["id"], visibility="private", title="Secret")
    async with pool.acquire() as conn:
        await conn.execute("UPDATE sources SET last_scraped_at = now() WHERE novel_id = $1;", en_codex)

    # Baseline: all three public novels, never the private one.
    base = (await routes.api_discover(user=reader))["items"]
    base_ids = {n["id"] for n in base}
    assert {en_codex, ja_raw, tagged} <= base_ids
    assert private_other not in base_ids

    # Language filter.
    ja = (await routes.api_discover(user=reader, language="ja"))["items"]
    assert {n["id"] for n in ja} == {ja_raw}

    # has_codex filter.
    codex = (await routes.api_discover(user=reader, has_codex=True))["items"]
    assert {n["id"] for n in codex} == {en_codex}

    # Tag filter.
    fant = (await routes.api_discover(user=reader, tag="fantasy"))["items"]
    assert {n["id"] for n in fant} == {tagged}

    # Translation filter: 'raws' selects raw-only sources.
    raws = (await routes.api_discover(user=reader, translation="raws"))["items"]
    assert {n["id"] for n in raws} == {ja_raw}

    # Freshness filter: only novels with a recently scraped source.
    fresh = (await routes.api_discover(user=reader, freshness="fresh_7d"))["items"]
    assert {n["id"] for n in fresh} == {en_codex}

    # Provenance-ish fields are present.
    row = next(n for n in base if n["id"] == en_codex)
    assert row["has_codex"] is True and row["translation_type"] == "translated"


@pytest.mark.asyncio
async def test_discover_has_audio_requires_current_shared_audio(db):
    pool, reader, other = db["pool"], db["reader"], db["other"]
    current = await _mk_novel(pool, owner_id=other["id"], title="CurrentAudio")
    stale = await _mk_novel(pool, owner_id=other["id"], title="OldAudio")
    quiet = await _mk_novel(pool, owner_id=other["id"], title="NoAudio")
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO chapter_audio (novel_id, chapter, voice_id, content_version, audio_path, user_id) "
            "VALUES ($1, 1, 'max', 1, 'cur.opus', NULL);", current)
        await conn.execute("UPDATE chapters SET content_version = 2 WHERE novel_id = $1 AND number = 1;", stale)
        await conn.execute(
            "INSERT INTO chapter_audio (novel_id, chapter, voice_id, content_version, audio_path, user_id) "
            "VALUES ($1, 1, 'narrator', 1, 'old.opus', NULL);", stale)

    audio = (await routes.api_discover(user=reader, has_audio=True))["items"]
    ids = {n["id"] for n in audio}
    assert current in ids
    assert stale not in ids and quiet not in ids


# ── Recap clamps to trusted ceiling ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_recap_clamps_to_effective_ceiling(db, monkeypatch):
    pool, reader, other = db["pool"], db["reader"], db["other"]
    nid = await _mk_novel(pool, owner_id=other["id"], title="Deep", chapters=5, codex=True)
    await _add_library(pool, reader["id"], nid)
    # Reader has only truly read up to chapter 2 (server-trusted); book has 5 chapters.
    await _set_progress(pool, reader["id"], nid, 2, 2)

    captured = {}

    async def _fake_answer(novel_id, question, ceiling):
        captured["ceiling"] = ceiling
        captured["question"] = question
        return {"answer": "Recap so far.", "citations": [], "evidence_ids": {}}

    monkeypatch.setattr(prod, "answer_question", _fake_answer)
    monkeypatch.setattr(prod, "get_bm25_manager", lambda _nid: _FakeBm25())

    # Even though the client asks for ceiling 5, the model is only ever run at the trusted 2.
    resp = await prod.api_recap(nid, prod.RecapRequest(ceiling=5), user=reader)
    assert captured["ceiling"] == 2, "recap must not run the model above trusted progress"
    assert resp["effective_ceiling"] == 2
    assert resp["ceiling_clamped"] is True
    assert resp["answer"] == "Recap so far."


@pytest.mark.asyncio
async def test_recap_cache_hit_is_free(db, monkeypatch):
    pool, reader, other = db["pool"], db["reader"], db["other"]
    nid = await _mk_novel(pool, owner_id=other["id"], title="Cached", chapters=3, codex=True)
    await _add_library(pool, reader["id"], nid)
    await _set_progress(pool, reader["id"], nid, 3, 3)

    from novelwiki.agent.orchestrator import compute_query_hash
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO query_cache (novel_id, query_hash, chapter_ceiling, answer_md, evidence_ids, created_at) "
            "VALUES ($1, $2, $3, $4, '{}'::jsonb, now());",
            nid, compute_query_hash(prod.RECAP_QUESTION), 3, "A cached recap.")

    def _boom(*a, **k):
        raise AssertionError("cache hit must not touch providers/bm25")

    async def _boom_rate(*a, **k):
        raise AssertionError("cache hit must not consume rate")

    monkeypatch.setattr(prod, "answer_question", _boom)
    monkeypatch.setattr(prod, "get_bm25_manager", _boom)
    monkeypatch.setattr(ai_limits, "consume_ask_rate", _boom_rate)

    resp = await prod.api_recap(nid, prod.RecapRequest(ceiling=3), user=reader)
    assert resp["answer"] == "A cached recap."


# ── Cost estimate respects quota, charges nothing ─────────────────────────────

@pytest.mark.asyncio
async def test_cost_estimate_translate_and_quota(db):
    pool, reader, other = db["pool"], db["reader"], db["other"]
    # A raw novel: 3 chapters, last one untranslated (content NULL) → 1 pending translate.
    nid = await _mk_novel(pool, owner_id=reader["id"], visibility="private", title="Raw",
                          chapters=3, raw=True, eng=False)
    # Give the reader a tiny translated-chapters quota and record some prior usage.
    import datetime as dt
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET quota_translated_chapters = 10 WHERE id = $1;", reader["id"])
        await conn.execute(
            "INSERT INTO quota_usage (user_id, period, translated_chapters) VALUES ($1, $2, 4);",
            reader["id"], dt.date.today().replace(day=1))
    # Re-read the user so the quota override is reflected in the dict the endpoint sees.
    async with pool.acquire() as conn:
        reader = dict(await conn.fetchrow("SELECT * FROM users WHERE id = $1;", reader["id"]))

    est = await prod.api_cost_estimate(nid, action="translate", user=reader)
    assert est["quota_kind"] == "translated_chapters"
    assert est["estimated_units"] == 1
    assert est["limit"] == 10 and est["remaining"] == 6   # 10 - 4 used
    assert est["allowed"] is True

    # Nothing was charged by estimating.
    async with pool.acquire() as conn:
        used = await conn.fetchval(
            "SELECT translated_chapters FROM quota_usage WHERE user_id = $1;", reader["id"])
    assert used == 4

    codex_est = await prod.api_cost_estimate(nid, action="codex_build", user=reader)
    assert codex_est["estimated_units"] == 1 and codex_est["quota_kind"] == "codex_builds"


@pytest.mark.asyncio
async def test_cost_estimate_audiobook_missing_count(db):
    pool, reader, other = db["pool"], db["reader"], db["other"]
    nid = await _mk_novel(pool, owner_id=reader["id"], visibility="private", title="Audio", chapters=4)
    async with pool.acquire() as conn:
        # One of four chapters already narrated in voice v1.
        await conn.execute(
            "INSERT INTO chapter_audio (novel_id, chapter, voice_id, content_version, audio_path, user_id) "
            "VALUES ($1, 1, 'v1', 1, 'a.opus', NULL);", nid)
    est = await prod.api_cost_estimate(nid, action="audiobook", voice_id="v1", user=reader)
    assert est["estimated_units"] == 3 and est["quota_kind"] == "tts_chapters"


@pytest.mark.asyncio
async def test_audio_coverage_and_selected_voice_chapters(db):
    pool, reader, other = db["pool"], db["reader"], db["other"]
    nid = await _mk_novel(pool, owner_id=reader["id"], visibility="private", title="Coverage", chapters=2)
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO chapter_audio (novel_id, chapter, voice_id, content_version, audio_path, user_id) "
            "VALUES ($1, 1, 'v1', 1, 'v1-1.opus', NULL);", nid)
        await conn.execute(
            "INSERT INTO chapter_audio (novel_id, chapter, voice_id, content_version, audio_path, user_id) "
            "VALUES ($1, 2, 'v2', 1, 'v2-2.opus', NULL);", nid)
        await conn.execute("UPDATE chapters SET content_version = 2 WHERE novel_id = $1 AND number = 2;", nid)
        await conn.execute(
            "INSERT INTO chapter_audio (novel_id, chapter, voice_id, content_version, audio_path, user_id) "
            "VALUES ($1, 2, 'v1', 1, 'stale.opus', NULL);", nid)

    coverage = await tts_routes.api_novel_audio_coverage(nid, user=reader)
    assert coverage["prose_chapters"] == 2
    assert coverage["chapters_with_any_audio"] == 1
    assert coverage["missing_any"] == 1
    assert coverage["chapters"] == [{"chapter": 1.0, "voices": ["v1"]}]

    selected = await tts_routes.api_novel_audio_chapters(nid, voice_id="v1", user=reader)
    assert selected["chapters"] == [1.0]


@pytest.mark.asyncio
async def test_chapter_audio_status_reports_available_other_voices(db):
    pool, reader, other = db["pool"], db["reader"], db["other"]
    nid = await _mk_novel(pool, owner_id=reader["id"], visibility="private", title="Status", chapters=1)
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO chapter_audio (novel_id, chapter, voice_id, content_version, audio_path, user_id) "
            "VALUES ($1, 1, 'v2', 1, 'v2.opus', NULL);", nid)

    missing_selected = await tts_routes.api_chapter_audio_status(nid, 1, voice_id="v1", user=reader)
    assert missing_selected["cached"] is False
    assert missing_selected["any_cached"] is True
    assert missing_selected["available_voices"] == ["v2"]

    cached_selected = await tts_routes.api_chapter_audio_status(nid, 1, voice_id="v2", user=reader)
    assert cached_selected["cached"] is True
    assert cached_selected["any_cached"] is True
    assert cached_selected["available_voices"] == ["v2"]


# ── Health panel counts ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_counts(db):
    pool, reader, other = db["pool"], db["reader"], db["other"]
    nid = await _mk_novel(pool, owner_id=reader["id"], visibility="private", title="Health",
                          chapters=4, raw=True, eng=False, codex=True)
    # raw novel seeded above leaves the last chapter untranslated → 1 untranslated_raw.
    async with pool.acquire() as conn:
        # Codex extracted only up to chapter 2 while the book has 4 → stale.
        await conn.execute(
            "INSERT INTO entities (novel_id, canonical_name, type, first_seen_chapter) "
            "VALUES ($1, 'Hero', 'character', 1);", nid)
        await conn.execute(
            "INSERT INTO chunks (novel_id, chapter, chunk_index, text) "
            "VALUES ($1, 1, 0, 'a'), ($1, 2, 0, 'b');", nid)
        await conn.execute(
            "INSERT INTO chapter_audio (novel_id, chapter, voice_id, content_version, audio_path, user_id) "
            "VALUES ($1, 1, 'v1', 1, 'a.opus', NULL);", nid)

    h = await prod.api_novel_health(nid, voice_id="v1", user=reader)
    assert h["untranslated_raw_chapters"] == 1
    assert h["codex"]["entities"] == 1
    assert h["codex"]["stale"] is True and h["codex"]["missing"] is False
    assert h["codex"]["coverage_chapter"] == 2.0
    assert h["audio"]["prose_chapters"] == 4 and h["audio"]["have"] == 1 and h["audio"]["missing"] == 3
    assert h["audio"]["voices"][0]["voice_id"] == "v1"
    assert h["is_editor"] is True


@pytest.mark.asyncio
async def test_health_audio_is_voice_agnostic_for_non_default_voice(db):
    pool, reader, other = db["pool"], db["reader"], db["other"]
    nid = await _mk_novel(pool, owner_id=reader["id"], visibility="private", title="NonDefault", chapters=3)
    async with pool.acquire() as conn:
        for ch in (1, 2, 3):
            await conn.execute(
                "INSERT INTO chapter_audio (novel_id, chapter, voice_id, content_version, audio_path, user_id) "
                "VALUES ($1, $2, 'max', 1, $3, NULL);", nid, ch, f"max-{ch}.opus")

    h = await prod.api_novel_health(nid, user=reader)
    assert h["audio"]["voice_id"] is None
    assert h["audio"]["have"] == 3
    assert h["audio"]["missing"] == 0
    assert h["audio"]["voices"] == [{
        "voice_id": "max",
        "have": 3,
        "missing": 0,
        "chapters": [1.0, 2.0, 3.0],
        "duration_seconds": 0,
        "file_bytes": 0,
    }]


@pytest.mark.asyncio
async def test_health_audio_split_across_voices_has_no_big_picture_gap(db):
    pool, reader, other = db["pool"], db["reader"], db["other"]
    nid = await _mk_novel(pool, owner_id=reader["id"], visibility="private", title="Split", chapters=2)
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO chapter_audio (novel_id, chapter, voice_id, content_version, audio_path, user_id) "
            "VALUES ($1, 1, 'narrator', 1, 'n1.opus', NULL);", nid)
        await conn.execute(
            "INSERT INTO chapter_audio (novel_id, chapter, voice_id, content_version, audio_path, user_id) "
            "VALUES ($1, 2, 'max', 1, 'm2.opus', NULL);", nid)

    h = await prod.api_novel_health(nid, user=reader)
    assert h["audio"]["missing"] == 0
    voices = {v["voice_id"]: v for v in h["audio"]["voices"]}
    assert voices["narrator"]["have"] == 1 and voices["narrator"]["missing"] == 1
    assert voices["max"]["have"] == 1 and voices["max"]["missing"] == 1


@pytest.mark.asyncio
async def test_health_missing_codex_when_enabled_but_empty(db):
    pool, reader, other = db["pool"], db["reader"], db["other"]
    nid = await _mk_novel(pool, owner_id=reader["id"], visibility="private", title="NoCodex",
                          chapters=3, codex=True)
    h = await prod.api_novel_health(nid, user=reader)
    assert h["codex"]["missing"] is True and h["codex"]["entities"] == 0


# ── Activity feed is scoped to the caller ─────────────────────────────────────

@pytest.mark.asyncio
async def test_activity_scoped_to_own_jobs(db):
    pool, reader, other = db["pool"], db["reader"], db["other"]
    nid = await _mk_novel(pool, owner_id=reader["id"], visibility="private", title="Jobs")
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO jobs (kind, novel_id, user_id, status, stage) "
            "VALUES ('scrape', $1, $2, 'running', 'scraping');", nid, reader["id"])
        await conn.execute(
            "INSERT INTO jobs (kind, novel_id, user_id, status, stage) "
            "VALUES ('scrape', $1, $2, 'running', 'scraping');", nid, other["id"])

    feed = await prod.api_activity(user=reader)
    assert len(feed["jobs"]) == 1
    assert feed["jobs"][0]["source"] == "job" and feed["jobs"][0]["cancelable"] is True


@pytest.mark.asyncio
async def test_activity_active_import_not_hidden_by_newer_done_imports(db):
    pool, reader, other = db["pool"], db["reader"], db["other"]
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO import_jobs (format, original_path, status, user_id, updated_at) "
            "VALUES ('epub', '/tmp/active.epub', 'uploaded', $1, now() - interval '2 days');",
            reader["id"])
        for i in range(5):
            await conn.execute(
                "INSERT INTO import_jobs (format, original_path, status, user_id, updated_at) "
                "VALUES ('epub', $1, 'committed', $2, now() - ($3::int * interval '1 minute'));",
                f"/tmp/done-{i}.epub", reader["id"], i)

    feed = await prod.api_activity(limit=1, user=reader)
    assert len(feed["jobs"]) == 1
    assert feed["jobs"][0]["source"] == "import"
    assert feed["jobs"][0]["status"] == "uploaded"
