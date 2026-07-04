"""Batch 5 regressions: resumable-upload DoS guards + atomic import-worker claiming.

Two clusters:

1. Chunked-upload hardening — the init/chunk/complete routes must bound disk use up front,
   refuse gaps (no sparse files), refuse writes past the declared size, hash by streaming
   (never ``read_bytes`` a whole blob into memory), and GC abandoned sessions.
2. Import-worker claiming — ``_claim_next`` must hand a job to exactly one worker (atomic
   ``FOR UPDATE SKIP LOCKED``), mapping each trigger status to a distinct in-progress marker,
   with restart + stale-lease recovery returning interrupted jobs to their trigger status.

Everything runs against the disposable ``tg_pytest_*`` database the conftest routes to; the
on-disk roots are redirected into a tmp dir so no real import scratch is touched.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import os

import pytest
import pytest_asyncio
from fastapi import HTTPException

import novelwiki.db.connection as db_connection
from novelwiki.api import routes
from novelwiki.config.settings import settings
from novelwiki.db.connection import close_db_pool, get_db_pool
from novelwiki.db.schema import init_database
from novelwiki.importer import jobs as import_jobs
from novelwiki.importer import storage


class _FakeRequest:
    """Minimal stand-in for the chunk route's ``Request`` (only headers + stream are read)."""

    def __init__(self, offset: int, body: bytes):
        self.headers = {"Upload-Offset": str(offset)}
        self._body = body

    async def stream(self):
        yield self._body


class _FakeUpload:
    def __init__(self, filename: str, chunks: list[bytes]):
        self.filename = filename
        self._chunks = list(chunks)
        self.read_sizes: list[int] = []

    async def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        if not self._chunks:
            return b""
        return self._chunks.pop(0)


async def _reset_pool():
    try:
        await close_db_pool()
    except RuntimeError:
        pass
    db_connection._pool = None


@pytest_asyncio.fixture()
async def upload_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "IMPORT_DIR", str(tmp_path / "imports"))
    monkeypatch.setattr(settings, "IMPORT_INCOMING_DIR", str(tmp_path / "imports" / "incoming"))
    monkeypatch.setattr(settings, "ASSET_DIR", str(tmp_path / "assets"))
    storage.ensure_dirs()
    await _reset_pool()
    await init_database()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM import_jobs;")
            await conn.execute("DELETE FROM tts_jobs;")
            await conn.execute("DELETE FROM novels CASCADE;")
            await conn.execute("DELETE FROM users CASCADE;")
            user = await conn.fetchrow(
                """
                INSERT INTO users (email, username, display_name, role, email_verified)
                VALUES ('uploader@example.test', 'uploader', 'Uploader', 'user', TRUE)
                RETURNING *;
                """
            )
    yield {"user": dict(user)}
    await _reset_pool()


async def _init(user: dict, filename: str = "book.epub", size: int = 1000) -> dict:
    return await routes.api_import_upload_init(
        routes.ImportInit(filename=filename, size=size), user=user
    )


async def _job_count() -> int:
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        return int(await conn.fetchval("SELECT count(*) FROM import_jobs;"))


# ── init: total-size enforcement ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_oversized_chunked_init_rejected(upload_db):
    too_big = settings.MAX_CHUNKED_UPLOAD_MB * 1024 * 1024 + 1
    with pytest.raises(HTTPException) as exc:
        await _init(upload_db["user"], size=too_big)
    assert exc.value.status_code == 413
    assert await _job_count() == 0          # rejected before any job/file was created


@pytest.mark.asyncio
async def test_zero_declared_size_rejected(upload_db):
    with pytest.raises(HTTPException) as exc:
        await _init(upload_db["user"], size=0)
    assert exc.value.status_code == 422
    assert await _job_count() == 0


@pytest.mark.asyncio
async def test_unknown_extension_rejected_before_job(upload_db):
    with pytest.raises(HTTPException) as exc:
        await _init(upload_db["user"], filename="malware.exe", size=1000)
    assert exc.value.status_code == 400
    assert await _job_count() == 0


@pytest.mark.asyncio
async def test_single_shot_upload_streams_and_cleans_up_oversize(upload_db, monkeypatch):
    user = upload_db["user"]
    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 1)
    upload = _FakeUpload("large.epub", [b"a" * (1024 * 1024), b"b"])

    with pytest.raises(HTTPException) as exc:
        await routes.api_import_upload(upload, user=user)

    assert exc.value.status_code == 413
    assert await _job_count() == 0
    assert upload.read_sizes and all(n > 0 for n in upload.read_sizes)
    assert "await file.read()" not in inspect.getsource(routes.api_import_upload)


# ── chunk: contiguity + bounds ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_chunk_beyond_eof_rejected_no_sparse_file(upload_db):
    user = upload_db["user"]
    jid = (await _init(user, size=100))["id"]
    r = await routes.api_import_upload_chunk(jid, _FakeRequest(0, b"x" * 10), user=user)
    assert r["offset"] == 10

    with pytest.raises(HTTPException) as exc:
        await routes.api_import_upload_chunk(jid, _FakeRequest(50, b"y" * 10), user=user)
    assert exc.value.status_code == 409
    # The gap was refused, so the on-disk blob is still exactly the 10 contiguous bytes.
    assert storage.upload_offset(jid, "epub") == 10


@pytest.mark.asyncio
async def test_chunk_exceeding_declared_total_rejected(upload_db):
    user = upload_db["user"]
    jid = (await _init(user, size=20))["id"]
    await routes.api_import_upload_chunk(jid, _FakeRequest(0, b"a" * 10), user=user)

    with pytest.raises(HTTPException) as exc:
        await routes.api_import_upload_chunk(jid, _FakeRequest(10, b"b" * 20), user=user)
    assert exc.value.status_code == 413
    assert storage.upload_offset(jid, "epub") == 10


@pytest.mark.asyncio
async def test_empty_chunk_rejected(upload_db):
    user = upload_db["user"]
    jid = (await _init(user, size=100))["id"]
    with pytest.raises(HTTPException) as exc:
        await routes.api_import_upload_chunk(jid, _FakeRequest(0, b""), user=user)
    assert exc.value.status_code == 400
    assert "request.body" not in inspect.getsource(routes.api_import_upload_chunk)


@pytest.mark.asyncio
async def test_idempotent_rechunk_is_noop(upload_db):
    user = upload_db["user"]
    jid = (await _init(user, size=100))["id"]
    assert (await routes.api_import_upload_chunk(jid, _FakeRequest(0, b"a" * 10), user=user))["offset"] == 10
    # Resending the SAME bytes already fully received is accepted without rewriting/growing.
    r = await routes.api_import_upload_chunk(jid, _FakeRequest(0, b"a" * 10), user=user)
    assert r["offset"] == 10
    assert storage.upload_offset(jid, "epub") == 10


@pytest.mark.asyncio
async def test_conflicting_rechunk_rejected(upload_db):
    user = upload_db["user"]
    jid = (await _init(user, size=100))["id"]
    await routes.api_import_upload_chunk(jid, _FakeRequest(0, b"a" * 10), user=user)
    # A retry that fully overlaps received bytes but with DIFFERENT content is a conflict, not
    # a silent no-op — the byte comparison catches the buggy client instead of masking it.
    with pytest.raises(HTTPException) as exc:
        await routes.api_import_upload_chunk(jid, _FakeRequest(0, b"b" * 10), user=user)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_accepted_chunk_keeps_session_from_being_gc_d(upload_db):
    # A resumed upload that has been open a long time but is STILL receiving chunks must not be
    # GC'd as abandoned: each accepted chunk bumps updated_at, so it stays out of the sweep.
    user = upload_db["user"]
    jid = (await _init(user, size=100))["id"]
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE import_jobs SET updated_at = now() - interval '48 hours' WHERE id = $1;", jid)
    await routes.api_import_upload_chunk(jid, _FakeRequest(0, b"q" * 10), user=user)   # fresh chunk

    await import_jobs._cleanup_stale_uploads()
    assert await import_jobs.get_job(jid) is not None            # survived — still active
    assert storage.original_path(jid, "epub").exists()


# ── complete: streaming hash + completeness ──────────────────────────────────

@pytest.mark.asyncio
async def test_completion_before_all_bytes_returns_400(upload_db):
    user = upload_db["user"]
    jid = (await _init(user, size=100))["id"]
    await routes.api_import_upload_chunk(jid, _FakeRequest(0, b"z" * 50), user=user)

    with pytest.raises(HTTPException) as exc:
        await routes.api_import_upload_complete(jid, user=user)
    assert exc.value.status_code == 400
    job = await import_jobs.get_job(jid)
    assert job["status"] == "receiving"     # left open, not marked uploaded


@pytest.mark.asyncio
async def test_completion_streams_large_file_without_read_bytes(upload_db):
    user = upload_db["user"]
    data = os.urandom(3 * 1024 * 1024)      # larger than the 1 MiB streaming block
    jid = (await _init(user, size=len(data)))["id"]
    await routes.api_import_upload_chunk(jid, _FakeRequest(0, data), user=user)

    res = await routes.api_import_upload_complete(jid, user=user)
    assert res["status"] == "uploaded"
    job = await import_jobs.get_job(jid)
    assert job["status"] == "uploaded"
    assert job["file_sha256"] == hashlib.sha256(data).hexdigest()
    # The implementation must not slurp the whole blob into memory.
    assert "read_bytes" not in inspect.getsource(storage.finalize_upload)


# ── abandoned-session GC ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_abandoned_receiving_session_is_cleaned_up(upload_db):
    user = upload_db["user"]
    jid = (await _init(user, size=100))["id"]
    await routes.api_import_upload_chunk(jid, _FakeRequest(0, b"p" * 10), user=user)
    blob = storage.original_path(jid, "epub")
    assert blob.exists()

    pool = await get_db_pool()
    async with pool.acquire() as conn:      # age it past the TTL
        await conn.execute(
            "UPDATE import_jobs SET updated_at = now() - interval '48 hours' WHERE id = $1;", jid
        )
    await import_jobs._cleanup_stale_uploads()

    assert await import_jobs.get_job(jid) is None    # row gone
    assert not blob.exists()                          # blob gone
    assert not blob.parent.exists()                   # scratch dir gone


@pytest.mark.asyncio
async def test_cleanup_leaves_fresh_and_active_jobs_alone(upload_db):
    user = upload_db["user"]
    fresh = (await _init(user, size=100))["id"]
    active = await import_jobs.create_job("epub", "/tmp/a.epub", status="uploaded", user_id=user["id"])
    await import_jobs._cleanup_stale_uploads()
    assert await import_jobs.get_job(fresh) is not None      # too young to GC
    assert await import_jobs.get_job(active) is not None      # not a receiving session


# ── atomic claiming ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_concurrent_claim_returns_job_to_exactly_one_caller(upload_db):
    uid = upload_db["user"]["id"]
    jid = await import_jobs.create_job("epub", "/tmp/x.epub", status="uploaded", user_id=uid)

    r1, r2 = await asyncio.gather(import_jobs._claim_next(), import_jobs._claim_next())
    claimed = [r for r in (r1, r2) if r is not None]
    assert len(claimed) == 1
    assert int(claimed[0]["id"]) == jid
    assert claimed[0]["status"] == "parsing"          # uploaded → parsing on claim
    # Once claimed, the job has left the trigger queue and can't be re-claimed.
    assert await import_jobs._claim_next() is None


@pytest.mark.asyncio
async def test_claim_maps_each_trigger_to_its_in_progress_marker(upload_db):
    uid = upload_db["user"]["id"]
    await import_jobs.create_job("epub", "/tmp/a.epub", status="uploaded", user_id=uid)
    await import_jobs.create_job("pdf", "/tmp/b.pdf", status="ocr_pending", user_id=uid)
    await import_jobs.create_job("epub", "/tmp/c.epub", status="committing", user_id=uid)

    seen = set()
    for _ in range(3):
        job = await import_jobs._claim_next()
        assert job is not None
        seen.add(job["status"])
    assert seen == {"parsing", "ocr_running", "commit_running"}
    assert await import_jobs._claim_next() is None


@pytest.mark.asyncio
async def test_lease_expiry_recovers_all_markers(upload_db):
    uid = upload_db["user"]["id"]
    ids = {}
    for status in ("parsing", "segmenting", "ocr_running", "commit_running"):
        ids[status] = await import_jobs.create_job("epub", f"/tmp/{status}.epub", status=status, user_id=uid)
    # Simulate a dead worker: every marker carries a claim whose lease expired long ago.
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE import_jobs SET claim_token = 'dead-worker', claimed_at = now() - interval '1 hour';"
        )
    await import_jobs._recover_stale_leases()

    assert (await import_jobs.get_job(ids["parsing"]))["status"] == "uploaded"
    assert (await import_jobs.get_job(ids["segmenting"]))["status"] == "uploaded"
    assert (await import_jobs.get_job(ids["ocr_running"]))["status"] == "ocr_pending"
    reclaimed = await import_jobs.get_job(ids["commit_running"])
    assert reclaimed["status"] == "committing"
    assert reclaimed["claim_token"] is None and reclaimed["claimed_at"] is None   # claim cleared


@pytest.mark.asyncio
async def test_null_lease_marker_is_reclaimed(upload_db):
    # A marker with no lease at all (orphaned, e.g. a legacy row) is reclaimable immediately.
    uid = upload_db["user"]["id"]
    jid = await import_jobs.create_job("epub", "/tmp/orphan.epub", status="commit_running", user_id=uid)
    await import_jobs._recover_stale_leases()
    assert (await import_jobs.get_job(jid))["status"] == "committing"


@pytest.mark.asyncio
async def test_live_claim_survives_recovery_even_with_old_updated_at(upload_db):
    # THE multi-worker safety property: recovery keys on the lease (`claimed_at`), NOT on
    # `updated_at`. A worker actively heartbeating a long OCR job keeps a fresh lease, so even
    # though the row's `updated_at` is hours old it must NOT be yanked out from under it.
    uid = upload_db["user"]["id"]
    jid = await import_jobs.create_job("pdf", "/tmp/live.pdf", status="ocr_running", user_id=uid)
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE import_jobs SET claim_token = 'live-worker', claimed_at = now(), "
            "updated_at = now() - interval '2 hours' WHERE id = $1;", jid
        )
    await import_jobs._recover_stale_leases()
    assert (await import_jobs.get_job(jid))["status"] == "ocr_running"    # untouched


@pytest.mark.asyncio
async def test_claim_stamps_lease_and_heartbeat_renews_it(upload_db):
    uid = upload_db["user"]["id"]
    await import_jobs.create_job("epub", "/tmp/x.epub", status="uploaded", user_id=uid)
    job = await import_jobs._claim_next()
    assert job["claim_token"] == import_jobs._WORKER_ID and job["claimed_at"] is not None

    # A renewal by the owning token bumps the lease; a wrong token is a no-op (can't steal it).
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE import_jobs SET claimed_at = now() - interval '1 hour' WHERE id = $1;", job["id"])
    await import_jobs._renew_lease(int(job["id"]), "someone-else")
    stale = await import_jobs.get_job(int(job["id"]))
    await import_jobs._renew_lease(int(job["id"]), job["claim_token"])
    renewed = await import_jobs.get_job(int(job["id"]))
    assert renewed["claimed_at"] > stale["claimed_at"]


@pytest.mark.asyncio
async def test_tts_worker_claim_unaffected(upload_db):
    from novelwiki.tts import worker as tts_worker
    uid = upload_db["user"]["id"]
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        novel_id = await conn.fetchval(
            "INSERT INTO novels (title, owner_id) VALUES ('N', $1) RETURNING id;", uid
        )
        await conn.execute(
            "INSERT INTO tts_jobs (novel_id, user_id, scope, voice_id, status) "
            "VALUES ($1, $2, 'chapter', 'narrator', 'queued');",
            novel_id, uid,
        )
    job = await tts_worker._claim_next()
    assert job is not None and job["status"] == "generating"
    assert await tts_worker._claim_next() is None
