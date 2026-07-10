from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio

import novelwiki.db.connection as db_connection
from novelwiki import quota
from novelwiki.agy.codex import validate_extraction_output
from novelwiki.agy.errors import AgyValidationError
from novelwiki.agy.translation import validate_translation_output
from novelwiki.db.connection import close_db_pool, get_db_pool
from novelwiki.db.schema import init_database
from novelwiki.ingest.extract import chapter_source_sha256, commit_extraction_proposal
from novelwiki.jobs import service
from novelwiki.translate.translate import (
    SourceChangedError,
    commit_translation,
    reset_staged_translations,
    source_sha256,
    stage_translation_batch,
)


@pytest_asyncio.fixture()
async def workload_db():
    try: await close_db_pool()
    except RuntimeError: pass
    db_connection._pool = None
    await init_database(); pool = await get_db_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM audit_events; DELETE FROM ai_execution_runs; DELETE FROM jobs; "
                           "DELETE FROM quota_usage; DELETE FROM novels CASCADE; DELETE FROM users CASCADE;")
        user = await conn.fetchrow(
            "INSERT INTO users (email,username,status,email_verified) "
            "VALUES ('work@agy.test','agywork','active',TRUE) RETURNING *;"
        )
        await conn.execute(
            "INSERT INTO user_ai_backend_policies (user_id,agy_enabled,default_backend,agy_workloads) "
            "VALUES ($1,TRUE,'agy',ARRAY['translate_batch','codex_extract']::text[]);",
            user["id"],
        )
        novel = await conn.fetchval(
            "INSERT INTO novels (title,owner_id,visibility) VALUES ('AGY Workload',$1,'private') RETURNING id;",
            user["id"],
        )
        await conn.execute(
            "INSERT INTO chapters (novel_id,number,title,original_text,language,translation_status,content_version) "
            "VALUES ($1,1,'第一章','林轩走进山门。\n\n他说：“你好。”','zh','none',1);", novel,
        )
    yield {"pool": pool, "user": dict(user), "novel_id": int(novel)}
    await close_db_pool(); db_connection._pool = None


@pytest.mark.asyncio
async def test_staged_translation_commit_is_run_owned_and_consumes_reserved_quota(workload_db):
    user, novel = workload_db["user"], workload_db["novel_id"]
    await quota.check_and_reserve(user, "translated_chapters", 1)
    job_id, _ = await service.create_job(
        "translate", novel_id=novel, user_id=user["id"], options={},
        quota_kind="translated_chapters", quota_reserved=1,
        execution_backend="agy", backend_requested="agy",
    )
    run_id = uuid.uuid4()
    staged = await stage_translation_batch(novel, [1.0], run_id)
    assert len(staged) == 1
    ch = staged[0]
    result = await commit_translation(
        novel, 1.0, expected_source_hash=ch["source_sha256"],
        expected_content_version=ch["source_content_version"], translated_title="Chapter 1",
        translation='Lin Xuan entered the mountain gate.\n\nHe said, “Hello.”',
        new_terms=[{"source_term": "林轩", "translation": "Lin Xuan", "term_type": "name"}],
        model_label="agy:fake", run_id=run_id, job_id=job_id,
    )
    assert result["status"] == "done"
    async with workload_db["pool"].acquire() as conn:
        row = await conn.fetchrow("SELECT * FROM chapters WHERE novel_id=$1 AND number=1;", novel)
        consumed = await conn.fetchval("SELECT quota_consumed FROM jobs WHERE id=$1;", job_id)
        glossary = await conn.fetchval("SELECT translation FROM translation_glossary WHERE novel_id=$1 AND source_term='林轩';", novel)
    assert row["translation_status"] == "done" and row["translation_run_id"] == run_id
    assert row["content_version"] == 2 and consumed == 1 and glossary == "Lin Xuan"


@pytest.mark.asyncio
async def test_source_change_blocks_staged_commit_and_reset_recovers_reader_path(workload_db):
    novel = workload_db["novel_id"]; run_id = uuid.uuid4()
    ch = (await stage_translation_batch(novel, [1.0], run_id))[0]
    async with workload_db["pool"].acquire() as conn:
        await conn.execute("UPDATE chapters SET original_text='edited',content_version=2 WHERE novel_id=$1 AND number=1;", novel)
    with pytest.raises(SourceChangedError):
        await commit_translation(
            novel, 1.0, expected_source_hash=ch["source_sha256"],
            expected_content_version=ch["source_content_version"], translated_title="Chapter 1",
            translation="Edited", new_terms=[], model_label="agy:fake", run_id=run_id,
        )
    assert await reset_staged_translations(run_id) == 1
    async with workload_db["pool"].acquire() as conn:
        row = await conn.fetchrow("SELECT translation_status,translation_run_id FROM chapters WHERE novel_id=$1 AND number=1;", novel)
    assert row["translation_status"] == "failed" and row["translation_run_id"] is None


def _artifact(output: Path, name: str, content: bytes, role: str) -> dict:
    path = output / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
    return {"path": name, "sha256": hashlib.sha256(content).hexdigest(), "bytes": len(content),
            "media_type": "application/json" if name.endswith(".json") else "text/plain; charset=utf-8",
            "role": role}


def _manifest(output: Path, run_id: uuid.UUID, workload: str, artifacts: list[dict]):
    (output / "manifest.json").write_text(json.dumps({
        "schema_version": "1.0", "run_id": str(run_id), "workload": workload,
        "status": "complete", "artifacts": artifacts, "warnings": [],
        "completed_at": datetime.now(UTC).isoformat(),
    }))


def test_translation_contract_validates_chapter_snapshot_and_quality(tmp_path):
    output = tmp_path / "output"; output.mkdir(); run_id = uuid.uuid4()
    source = "林轩走进山门。\n\n他说你好。"
    staged = [{"number": 1.0, "title": "第一章", "original_text": source, "language": "zh",
               "source_sha256": source_sha256(source), "source_content_version": 1}]
    text = b'Lin Xuan entered the mountain gate.\n\nHe said hello.\n'
    meta = json.dumps({"schema_version": "1.0", "chapter_ref": "c000001",
        "source_sha256": staged[0]["source_sha256"], "source_content_version": 1,
        "translated_title": "Chapter 1", "translation_path": "c000001.translation.txt",
        "new_terms": [{"source_term": "林轩", "translation": "Lin Xuan", "term_type": "name"}],
        "self_review": {"complete": True, "paragraphs_preserved": True, "glossary_checked": True}}).encode()
    artifacts = [_artifact(output, "chapters/c000001.translation.txt", text, "translation"),
                 _artifact(output, "chapters/c000001.meta.json", meta, "translation_meta")]
    _manifest(output, run_id, "translate_batch", artifacts)
    proposals = validate_translation_output(tmp_path, run_id, staged, {
        "confirmed_mappings": [{"source_term": "林轩", "translation": "Lin Xuan", "locked": True}],
        "established_english_spellings": [],
    })
    assert proposals[0]["title"] == "Chapter 1"


def test_codex_contract_requires_supplied_provenance(tmp_path):
    output = tmp_path / "output"; output.mkdir(); run_id = uuid.uuid4()
    source = {"source_sha256": "a" * 64, "chunk_ids": {10}, "roster_map": {}}
    extraction = {"schema_version": "1.0", "chapter": 1.0, "source_sha256": "a" * 64,
        "mentions": [{"entity_ref": "m1", "surface_form": "Lin Xuan", "type": "character"}],
        "facts": [{"entity_ref": "m1", "fact_type": "action", "content": "Entered.", "source_chunk_ids": [10]}],
        "relationships": [], "events": [], "identity_reveals": [], "new_aliases": [], "warnings": []}
    artifacts = [_artifact(output, "extraction.json", json.dumps(extraction).encode(), "codex_extraction"),
                 _artifact(output, "running-summary.md", b"Lin Xuan entered.\n", "running_summary"),
                 _artifact(output, "audit.json", b'{"reviewed":true}', "codex_audit")]
    _manifest(output, run_id, "codex_extract", artifacts)
    data, summary = validate_extraction_output(tmp_path, run_id, 1.0, source)
    assert len(data["facts"]) == 1 and summary
    extraction["facts"][0]["source_chunk_ids"] = [999]
    content = json.dumps(extraction).encode(); (output / "extraction.json").write_bytes(content)
    manifest = json.loads((output / "manifest.json").read_text())
    manifest["artifacts"][0].update(bytes=len(content), sha256=hashlib.sha256(content).hexdigest())
    (output / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(AgyValidationError):
        validate_extraction_output(tmp_path, run_id, 1.0, source)


@pytest.mark.asyncio
async def test_codex_commit_is_idempotent_by_run_and_source_hash(workload_db):
    novel = workload_db["novel_id"]
    async with workload_db["pool"].acquire() as conn:
        await conn.execute("UPDATE chapters SET content='English chapter',original_text=NULL WHERE novel_id=$1 AND number=1;", novel)
        await conn.execute("INSERT INTO chunks (novel_id,chapter,chunk_index,text) VALUES ($1,1,0,'English chapter');", novel)
    run_id = uuid.uuid4(); digest = chapter_source_sha256("English chapter")
    result = await commit_extraction_proposal(
        novel, 1.0, {k: [] for k in ("mentions","facts","relationships","events","identity_reveals","new_aliases")},
        "Story begins.", expected_source_hash=digest, resolved_refs={}, run_id=run_id,
        model_label="agy:fake",
    )
    replay = await commit_extraction_proposal(
        novel, 1.0, {k: [] for k in ("mentions","facts","relationships","events","identity_reveals","new_aliases")},
        "Story begins.", expected_source_hash=digest, resolved_refs={}, run_id=run_id,
        model_label="agy:fake",
    )
    assert result["idempotent"] is False and replay["idempotent"] is True
