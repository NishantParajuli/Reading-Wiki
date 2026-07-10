from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import HTTPException

import novelwiki.db.connection as db_connection
from novelwiki.ai_backend.policy import delete_policy, resolve_backend, upsert_policy
from novelwiki.ai_backend.types import Workload
from novelwiki.api import routes
from novelwiki.config.settings import settings
from novelwiki.db.connection import close_db_pool, get_db_pool
from novelwiki.db.schema import init_database
from novelwiki.jobs import service, worker
from novelwiki.jobs.claims import claim_next


@pytest.mark.asyncio
async def test_global_switch_off_preserves_api_and_rejects_explicit_agy(monkeypatch):
    monkeypatch.setattr(settings, "AGY_ENABLED", False)
    user = {"id": 1, "status": "active", "role": "user"}
    auto = await resolve_backend(user, Workload.TRANSLATE_BATCH, "auto")
    assert auto.resolved.value == "api" and auto.reason == "global_disabled"
    explicit_api = await resolve_backend(user, Workload.TRANSLATE_BATCH, "api")
    assert explicit_api.resolved.value == "api"
    with pytest.raises(HTTPException) as exc:
        await resolve_backend(user, Workload.TRANSLATE_BATCH, "agy")
    assert exc.value.status_code == 503


@pytest_asyncio.fixture()
async def policy_db(monkeypatch):
    try:
        await close_db_pool()
    except RuntimeError:
        pass
    db_connection._pool = None
    await init_database()
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM audit_events; DELETE FROM ai_execution_runs; DELETE FROM jobs; "
                           "DELETE FROM quota_usage; DELETE FROM novels CASCADE; DELETE FROM users CASCADE;")
        admin = await conn.fetchrow(
            "INSERT INTO users (email,username,role,status,email_verified) "
            "VALUES ('admin@agy.test','agyadmin','admin','active',TRUE) RETURNING *;"
        )
        user = await conn.fetchrow(
            "INSERT INTO users (email,username,role,status,email_verified) "
            "VALUES ('user@agy.test','agyuser','user','active',TRUE) RETURNING *;"
        )
        novel_id = await conn.fetchval(
            "INSERT INTO novels (title,owner_id,visibility) VALUES ('AGY policy novel',$1,'private') RETURNING id;",
            user["id"],
        )
        await conn.executemany(
            "INSERT INTO chapters (novel_id,number,title,original_text,language,translation_status) "
            "VALUES ($1,$2,$3,$4,'zh','none');",
            [(novel_id, 1, "一", "第一章"), (novel_id, 2, "二", "第二章")],
        )
    monkeypatch.setattr(settings, "AGY_ENABLED", True)
    yield {"pool": pool, "admin": dict(admin), "user": dict(user), "novel_id": int(novel_id)}
    await close_db_pool(); db_connection._pool = None


@pytest.mark.asyncio
async def test_no_grant_and_matching_grant_selection(policy_db):
    user = policy_db["user"]
    auto = await resolve_backend(user, Workload.TRANSLATE_BATCH, "auto")
    assert auto.resolved.value == "api" and auto.reason == "not_granted"
    with pytest.raises(HTTPException) as exc:
        await resolve_backend(user, Workload.TRANSLATE_BATCH, "agy")
    assert exc.value.status_code == 403

    row = await upsert_policy(user["id"], {
        "agy_enabled": True, "default_backend": "agy", "agy_workloads": ["translate_batch"],
        "fallback_to_api": False, "max_concurrent_agy_jobs": 1,
    }, policy_db["admin"]["id"])
    assert int(row["policy_version"]) == 1
    decision = await resolve_backend(user, Workload.TRANSLATE_BATCH, "auto")
    assert decision.resolved.value == "agy" and decision.model == settings.AGY_MODEL_TRANSLATE
    assert (await resolve_backend(user, Workload.TRANSLATE_BATCH, "api")).resolved.value == "api"
    with pytest.raises(HTTPException):
        await resolve_backend(user, Workload.CODEX_EXTRACT, "agy")


@pytest.mark.asyncio
async def test_route_reserves_agy_batch_once_and_dedupes(policy_db):
    user, admin, novel_id = policy_db["user"], policy_db["admin"], policy_db["novel_id"]
    await upsert_policy(user["id"], {
        "agy_enabled": True, "default_backend": "agy", "agy_workloads": ["translate_batch"],
        "fallback_to_api": False, "max_concurrent_agy_jobs": 1,
    }, admin["id"])
    first = await routes.api_translate(novel_id, routes.TranslateTrigger(), user=user)
    assert first["execution_backend"] == "agy" and first["chapters"] == 2
    job = await service.get_job(first["job_id"])
    assert job["quota_reserved"] == 2 and job["backend_policy_version"] == 1
    second = await routes.api_translate(novel_id, routes.TranslateTrigger(ai_backend="api"), user=user)
    assert second["deduped"] is True and second["execution_backend"] == "agy"
    async with policy_db["pool"].acquire() as conn:
        usage = await conn.fetchval("SELECT translated_chapters FROM quota_usage WHERE user_id=$1;", user["id"])
    assert int(usage) == 2


@pytest.mark.asyncio
async def test_claim_capabilities_and_revocation(policy_db):
    user, admin, novel_id = policy_db["user"], policy_db["admin"], policy_db["novel_id"]
    await upsert_policy(user["id"], {
        "agy_enabled": True, "default_backend": "agy", "agy_workloads": ["translate_batch"],
        "fallback_to_api": False, "max_concurrent_agy_jobs": 1,
    }, admin["id"])
    agy_id, _ = await service.create_job(
        "translate", novel_id=novel_id, user_id=user["id"], options={},
        execution_backend="agy", backend_requested="agy", backend_policy_version=1,
    )
    assert await worker._claim_next() is None
    claimed = await claim_next(execution_backend="agy", worker_id="test-agy", kinds=("translate",))
    assert claimed["id"] == agy_id
    # Running AGY revocation becomes an active cancellation request, then the worker finalizes it.
    assert await delete_policy(user["id"], admin["id"]) is True
    row = await service.get_job(agy_id)
    assert row["status"] == "running" and row["cancel_requested_at"] is not None
    assert await service.mark_canceled_if_running(agy_id) is True
    assert (await service.get_job(agy_id))["status"] == "canceled"


@pytest.mark.asyncio
async def test_active_agy_concurrency_limit(policy_db):
    user, admin, novel_id = policy_db["user"], policy_db["admin"], policy_db["novel_id"]
    await upsert_policy(user["id"], {
        "agy_enabled": True, "default_backend": "agy", "agy_workloads": ["translate_batch"],
        "fallback_to_api": False, "max_concurrent_agy_jobs": 1,
    }, admin["id"])
    await service.create_job("translate", novel_id=novel_id, user_id=user["id"], options={},
                             execution_backend="agy", backend_requested="agy")
    with pytest.raises(HTTPException) as exc:
        await resolve_backend(user, Workload.TRANSLATE_BATCH, "agy")
    assert exc.value.status_code == 429
