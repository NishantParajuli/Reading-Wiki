"""Regression tests for Batch 8: durable generic jobs, refund semantics, and observability.

Covers the move of scrape / codex-build / translation off fire-and-forget ``BackgroundTasks`` onto
the durable ``jobs`` table + worker: scheduling creates a durable row (no BackgroundTasks), atomic
single-claim, idempotent dedupe of repeated codex clicks, stale-lease recovery on restart, quota
reservation/finalization/refund on failure & cancel, cooperative cancellation before the next
expensive stage, progress visible through the API, and the X-Request-ID response header.
"""
import pytest
import pytest_asyncio

import novelwiki.db.connection as db_connection
from novelwiki import quota
from novelwiki.api import routes
from novelwiki.config.settings import settings
from novelwiki.db.connection import close_db_pool, get_db_pool
from novelwiki.db.schema import init_database
from novelwiki.jobs import service, worker


async def _reset_pool():
    try:
        await close_db_pool()
    except RuntimeError:
        pass
    db_connection._pool = None


@pytest_asyncio.fixture()
async def jobs_db():
    await _reset_pool()
    await init_database()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM audit_events;")
            await conn.execute("DELETE FROM jobs;")
            await conn.execute("DELETE FROM quota_usage;")
            await conn.execute("DELETE FROM novels CASCADE;")
            await conn.execute("DELETE FROM users CASCADE;")

            owner = await conn.fetchrow(
                """
                INSERT INTO users (email, username, display_name, role, email_verified)
                VALUES ('owner@example.test', 'owner', 'Owner', 'user', TRUE) RETURNING *;
                """
            )
            novel_id = await conn.fetchval(
                "INSERT INTO novels (title, owner_id, visibility) VALUES ('Durable Jobs Novel', $1, 'private') RETURNING id;",
                owner["id"],
            )
            # One normal English chapter + one raw (has original_text, no content) for translate.
            await conn.executemany(
                "INSERT INTO chapters (novel_id, number, title, content, original_text, language, translation_status) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7);",
                [
                    (novel_id, 1, "One", "chapter one", None, "en", "done"),
                    (novel_id, 2, "Two (raw)", None, "第二章内容", "zh", "none"),
                    (novel_id, 3, "Three (raw)", None, "第三章内容", "zh", "none"),
                ],
            )
    yield {"pool": pool, "owner": dict(owner), "novel_id": novel_id}
    await _reset_pool()


async def _count_jobs(pool, **where) -> int:
    conds, args = [], []
    for k, v in where.items():
        args.append(v); conds.append(f"{k} = ${len(args)}")
    q = "SELECT count(*) FROM jobs" + (f" WHERE {' AND '.join(conds)}" if conds else "") + ";"
    async with pool.acquire() as conn:
        return int(await conn.fetchval(q, *args))


async def _usage(pool, user_id, kind) -> int:
    async with pool.acquire() as conn:
        v = await conn.fetchval(
            f"SELECT {kind} FROM quota_usage WHERE user_id = $1 AND period = date_trunc('month', now())::date;",
            user_id,
        )
    return int(v or 0)


# ── Scheduling creates durable jobs (no BackgroundTasks) ─────────────────────

@pytest.mark.asyncio
async def test_scrape_schedules_durable_job(jobs_db):
    novel_id = jobs_db["novel_id"]
    resp = await routes.api_scrape(novel_id, routes.ScrapeTrigger(max_chapters=5), user=jobs_db["owner"])
    assert resp["job_id"] and resp["deduped"] is False
    assert await _count_jobs(jobs_db["pool"], kind="scrape", status="queued") == 1
    job = await service.get_job(resp["job_id"])
    assert job["kind"] == "scrape" and job["options"]["max_chapters"] == 5


@pytest.mark.asyncio
async def test_translate_schedules_durable_job(jobs_db):
    novel_id = jobs_db["novel_id"]
    resp = await routes.api_translate(novel_id, routes.TranslateTrigger(), user=jobs_db["owner"])
    assert resp["job_id"] and resp["chapters"] == 2  # two raw chapters pending
    assert await _count_jobs(jobs_db["pool"], kind="translate", status="queued") == 1


@pytest.mark.asyncio
async def test_codex_build_reserves_and_dedupes(jobs_db):
    novel_id, owner = jobs_db["novel_id"], jobs_db["owner"]
    r1 = await routes.api_codex_build(novel_id, routes.CodexBuild(), user=owner)
    assert r1["deduped"] is False
    # A second identical click dedupes onto the same active job and does NOT charge again.
    r2 = await routes.api_codex_build(novel_id, routes.CodexBuild(), user=owner)
    assert r2["deduped"] is True and r2["job_id"] == r1["job_id"]
    assert await _count_jobs(jobs_db["pool"], kind="codex_build") == 1
    assert await _usage(jobs_db["pool"], owner["id"], "codex_builds") == 1


@pytest.mark.asyncio
async def test_scrape_dedupe_key_includes_force_and_max_chapters(jobs_db):
    novel_id, owner = jobs_db["novel_id"], jobs_db["owner"]
    r1 = await routes.api_scrape(novel_id, routes.ScrapeTrigger(max_chapters=5), user=owner)
    r2 = await routes.api_scrape(novel_id, routes.ScrapeTrigger(max_chapters=6), user=owner)
    r3 = await routes.api_scrape(novel_id, routes.ScrapeTrigger(max_chapters=5, force=True), user=owner)

    assert len({r1["job_id"], r2["job_id"], r3["job_id"]}) == 3
    assert r1["deduped"] is False and r2["deduped"] is False and r3["deduped"] is False
    assert await _count_jobs(jobs_db["pool"], kind="scrape", status="queued") == 3


@pytest.mark.asyncio
async def test_translate_dedupe_key_includes_seed_option(jobs_db):
    novel_id, owner = jobs_db["novel_id"], jobs_db["owner"]
    r1 = await routes.api_translate(novel_id, routes.TranslateTrigger(seed_from_codex=False), user=owner)
    r2 = await routes.api_translate(novel_id, routes.TranslateTrigger(seed_from_codex=True), user=owner)

    assert r1["job_id"] != r2["job_id"]
    assert r1["deduped"] is False and r2["deduped"] is False
    assert await _count_jobs(jobs_db["pool"], kind="translate", status="queued") == 2


# ── Atomic single-claim ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_worker_claims_one_job_atomically(jobs_db):
    novel_id, owner = jobs_db["novel_id"], jobs_db["owner"]
    id1, _ = await service.create_job("scrape", novel_id=novel_id, user_id=owner["id"], options={})
    id2, _ = await service.create_job("scrape", novel_id=novel_id, user_id=owner["id"], options={})

    a = await worker._claim_next()
    b = await worker._claim_next()
    c = await worker._claim_next()
    claimed = {a["id"], b["id"]}
    assert claimed == {id1, id2}            # each job claimed exactly once
    assert a["status"] == "running" and a["attempts"] == 1
    assert c is None                        # nothing left to claim


# ── Restart / stale-lease recovery ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_stale_lease_requeues_then_fails(jobs_db):
    novel_id, owner, pool = jobs_db["novel_id"], jobs_db["owner"], jobs_db["pool"]
    job_id, _ = await service.create_job("scrape", novel_id=novel_id, user_id=owner["id"], options={})
    claimed = await worker._claim_next()
    assert claimed["id"] == job_id and claimed["status"] == "running"

    # Simulate the owning worker vanishing: force the lease into the past.
    async with pool.acquire() as conn:
        await conn.execute("UPDATE jobs SET claimed_at = now() - interval '1 hour' WHERE id = $1;", job_id)

    await worker._recover_stale_leases()
    job = await service.get_job(job_id)
    assert job["status"] == "queued"        # attempts (1) < max → requeued

    # Now exhaust attempts and expire again → terminally failed.
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE jobs SET status='running', attempts=max_attempts, claimed_at=now() - interval '1 hour' WHERE id=$1;",
            job_id,
        )
    await worker._recover_stale_leases()
    job = await service.get_job(job_id)
    assert job["status"] == "failed"


# ── Quota finalization / refund ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_finalize_refunds_unconsumed_reservation(jobs_db):
    novel_id, owner, pool = jobs_db["novel_id"], jobs_db["owner"], jobs_db["pool"]
    assert await quota.try_reserve(owner, "codex_builds", 1) is True
    job_id, _ = await service.create_job(
        "codex_build", novel_id=novel_id, user_id=owner["id"], options={},
        quota_kind="codex_builds", quota_reserved=1,
    )
    assert await _usage(pool, owner["id"], "codex_builds") == 1

    # Failure → the whole reservation is refunded, exactly once.
    await service.finalize(job_id, success=False)
    assert await _usage(pool, owner["id"], "codex_builds") == 0
    await service.finalize(job_id, success=False)  # idempotent guard
    assert await _usage(pool, owner["id"], "codex_builds") == 0


@pytest.mark.asyncio
async def test_finalize_success_keeps_charge(jobs_db):
    novel_id, owner, pool = jobs_db["novel_id"], jobs_db["owner"], jobs_db["pool"]
    await quota.try_reserve(owner, "codex_builds", 1)
    job_id, _ = await service.create_job(
        "codex_build", novel_id=novel_id, user_id=owner["id"], options={},
        quota_kind="codex_builds", quota_reserved=1,
    )
    await service.finalize(job_id, success=True)
    assert await _usage(pool, owner["id"], "codex_builds") == 1  # a successful build spends its credit


@pytest.mark.asyncio
async def test_codex_job_failure_refunds_quota(jobs_db, monkeypatch):
    """End-to-end: a codex build that fails through the worker refunds its reserved credit."""
    novel_id, owner, pool = jobs_db["novel_id"], jobs_db["owner"], jobs_db["pool"]
    await quota.try_reserve(owner, "codex_builds", 1)
    job_id, _ = await service.create_job(
        "codex_build", novel_id=novel_id, user_id=owner["id"], options={},
        quota_kind="codex_builds", quota_reserved=1, max_attempts=1,
    )

    async def _boom(*a, **k):
        raise RuntimeError("provider exploded")
    monkeypatch.setattr("novelwiki.ingest.chunk.chunk_all_chapters", _boom)

    claimed = await worker._claim_next()
    await worker._process(claimed)

    job = await service.get_job(job_id)
    assert job["status"] == "failed" and job["quota_finalized"] is True
    assert await _usage(pool, owner["id"], "codex_builds") == 0


@pytest.mark.asyncio
async def test_cancel_queued_job_refunds(jobs_db):
    novel_id, owner, pool = jobs_db["novel_id"], jobs_db["owner"], jobs_db["pool"]
    await quota.try_reserve(owner, "codex_builds", 1)
    job_id, _ = await service.create_job(
        "codex_build", novel_id=novel_id, user_id=owner["id"], options={},
        quota_kind="codex_builds", quota_reserved=1,
    )
    assert await service.cancel_job(job_id) is True
    job = await service.get_job(job_id)
    assert job["status"] == "canceled"
    assert await _usage(pool, owner["id"], "codex_builds") == 0  # queued cancel refunds immediately


@pytest.mark.asyncio
async def test_cancel_running_job_refunds_even_if_worker_never_returns(jobs_db):
    """A cancel request is terminal/finalized on its own; it cannot rely on the claimed worker
    returning later, because a process crash after cancel would otherwise strand the reservation."""
    novel_id, owner, pool = jobs_db["novel_id"], jobs_db["owner"], jobs_db["pool"]
    await quota.try_reserve(owner, "codex_builds", 1)
    job_id, _ = await service.create_job(
        "codex_build", novel_id=novel_id, user_id=owner["id"], options={},
        quota_kind="codex_builds", quota_reserved=1,
    )
    claimed = await worker._claim_next()
    assert claimed["id"] == job_id and claimed["claim_token"]

    assert await service.cancel_job(job_id) is True
    job = await service.get_job(job_id)
    assert job["status"] == "canceled"
    assert job["quota_finalized"] is True
    assert job["claim_token"] is None and job["claimed_at"] is None
    assert await _usage(pool, owner["id"], "codex_builds") == 0


# ── Cooperative cancellation before the next expensive stage ──────────────────

@pytest.mark.asyncio
async def test_codex_cancel_stops_before_next_stage(jobs_db, monkeypatch):
    novel_id, owner, pool = jobs_db["novel_id"], jobs_db["owner"], jobs_db["pool"]
    await quota.try_reserve(owner, "codex_builds", 1)
    job_id, _ = await service.create_job(
        "codex_build", novel_id=novel_id, user_id=owner["id"], options={},
        quota_kind="codex_builds", quota_reserved=1,
    )
    embed_called = {"v": False}

    async def _chunk(*a, **k):
        # Cancellation lands while the first stage runs.
        await service.update_job(job_id, status="canceled")

    async def _embed(*a, **k):
        embed_called["v"] = True

    async def _extract(*a, **k):
        pass

    class _Bm:
        async def rebuild(self):
            pass

    monkeypatch.setattr("novelwiki.ingest.chunk.chunk_all_chapters", _chunk)
    monkeypatch.setattr("novelwiki.ingest.embed.embed_missing_chunks", _embed)
    monkeypatch.setattr("novelwiki.ingest.extract.extract_all_chapters", _extract)
    monkeypatch.setattr("novelwiki.retrieval.bm25.get_bm25_manager", lambda *_a, **_k: _Bm())

    claimed = await worker._claim_next()
    await worker._process(claimed)

    job = await service.get_job(job_id)
    assert job["status"] == "canceled"
    assert embed_called["v"] is False                     # stopped before the next expensive step
    assert await _usage(pool, owner["id"], "codex_builds") == 0  # unconsumed reservation refunded


@pytest.mark.asyncio
async def test_scrape_cancel_stops_before_next_source(jobs_db, monkeypatch):
    novel_id, owner, pool = jobs_db["novel_id"], jobs_db["owner"], jobs_db["pool"]
    async with pool.acquire() as conn:
        await conn.executemany(
            """
            INSERT INTO sources (novel_id, adapter, start_url, config, language, is_raw)
            VALUES ($1, 'fenrirealm', $2, '{}'::jsonb, 'en', FALSE);
            """,
            [
                (novel_id, "https://public.example/one"),
                (novel_id, "https://public.example/two"),
            ],
        )
    job_id, _ = await service.create_job(
        "scrape", novel_id=novel_id, user_id=owner["id"],
        options={"source_id": None, "force": False, "max_chapters": None},
    )
    called_sources = []

    async def _fake_scrape_source(source_id, *args, cancel_check=None, **kwargs):
        called_sources.append(source_id)
        await service.cancel_job(job_id)
        if cancel_check is not None:
            await cancel_check()
        raise AssertionError("cancel_check should raise before more scrape work happens")

    monkeypatch.setattr("novelwiki.scraper.runner.scrape_source", _fake_scrape_source)

    claimed = await worker._claim_next()
    await worker._process(claimed)

    job = await service.get_job(job_id)
    assert job["status"] == "canceled"
    assert len(called_sources) == 1


# ── Translation job runs, meters, reports progress ───────────────────────────

@pytest.mark.asyncio
async def test_translate_job_runs_and_reports_progress(jobs_db, monkeypatch):
    novel_id, owner = jobs_db["novel_id"], jobs_db["owner"]
    job_id, _ = await service.create_job(
        "translate", novel_id=novel_id, user_id=owner["id"],
        options={"from_chapter": None, "to_chapter": None, "force": False},
    )

    async def _fake_translate(nid, number, force=False, meter_user=None):
        if meter_user is not None:
            await quota.try_reserve(meter_user, "translated_chapters", 1)
        return {"status": "done", "content": "translated"}
    monkeypatch.setattr("novelwiki.translate.translate.translate_chapter", _fake_translate)

    claimed = await worker._claim_next()
    await worker._process(claimed)

    job = await service.get_job(job_id)
    assert job["status"] == "done"
    assert job["progress"]["total"] == 2 and job["progress"]["done"] == 2   # two raw chapters
    assert await _usage(jobs_db["pool"], owner["id"], "translated_chapters") == 2


@pytest.mark.asyncio
async def test_translate_provider_failure_refunds_reserved_chapter_quota(jobs_db, monkeypatch):
    novel_id, owner = jobs_db["novel_id"], jobs_db["owner"]
    job_id, _ = await service.create_job(
        "translate", novel_id=novel_id, user_id=owner["id"],
        options={"from_chapter": None, "to_chapter": None, "force": False},
    )

    async def _explode(*_args, **_kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr("novelwiki.translate.translate.call_chat_completion", _explode)

    claimed = await worker._claim_next()
    await worker._process(claimed)

    job = await service.get_job(job_id)
    assert job["status"] == "done"
    assert job["progress"]["failed"] == 2
    assert await _usage(jobs_db["pool"], owner["id"], "translated_chapters") == 0


# ── Progress + listing visible through the API ───────────────────────────────

@pytest.mark.asyncio
async def test_job_visible_through_api(jobs_db):
    novel_id, owner = jobs_db["novel_id"], jobs_db["owner"]
    r = await routes.api_scrape(novel_id, routes.ScrapeTrigger(), user=owner)
    listing = await routes.api_list_jobs(novel_id=novel_id, user=owner)
    assert any(j["id"] == r["job_id"] for j in listing["jobs"])
    one = await routes.api_get_job(r["job_id"], user=owner)
    assert one["id"] == r["job_id"] and one["kind"] == "scrape"


@pytest.mark.asyncio
async def test_other_user_cannot_see_or_cancel_job(jobs_db):
    from fastapi import HTTPException
    novel_id, owner, pool = jobs_db["novel_id"], jobs_db["owner"], jobs_db["pool"]
    r = await routes.api_scrape(novel_id, routes.ScrapeTrigger(), user=owner)
    async with pool.acquire() as conn:
        stranger = await conn.fetchrow(
            "INSERT INTO users (email, username, display_name, role, email_verified) "
            "VALUES ('s@example.test','stranger','S','user',TRUE) RETURNING *;"
        )
    with pytest.raises(HTTPException) as exc:
        await routes.api_get_job(r["job_id"], user=dict(stranger))
    assert exc.value.status_code == 404
    # A stranger's listing is scoped to their own jobs (none here).
    listing = await routes.api_list_jobs(user=dict(stranger))
    assert listing["jobs"] == []


# ── Request-id observability ─────────────────────────────────────────────────

def test_request_id_header_returned():
    from starlette.testclient import TestClient
    from novelwiki.api.app import app
    # No context manager → the app lifespan (and its workers) don't boot; /health needs no DB.
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200 and r.headers.get("x-request-id")
    echoed = client.get("/health", headers={"X-Request-ID": "trace-abc-123"})
    assert echoed.headers.get("x-request-id") == "trace-abc-123"
