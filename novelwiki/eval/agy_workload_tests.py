from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

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
from novelwiki.ingest.chunk import chunk_chapter
from novelwiki.jobs import service
from novelwiki.modules.ai_execution.adapters.outbound.worker_state import (
    PostgresAgyWorkerStateRepository,
)
from novelwiki.modules.codex.adapters.outbound.agy import (
    _checkpointed_job_chapters,
    _codex_task_document,
)
from novelwiki.modules.codex.adapters.outbound.context import (
    build_chapter_context, current_entity_state, current_relationship_state,
)
from novelwiki.modules.codex.adapters.outbound.ingest.link import merge_entities
from novelwiki.modules.codex.adapters.outbound.retrieval.tools import (
    get_entity_profile, get_timeline, list_entities,
)
from novelwiki.modules.reading.adapters.outbound.codex import PostgresReadingCodexGateway
from novelwiki.platform.config import settings
from novelwiki.modules.translation.adapters.outbound.agy import _translation_task_document
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


def test_agy_task_bundles_put_each_workload_in_one_exact_read():
    chapter = {
        "number": 1.0, "title": "First", "language": "zh",
        "source_sha256": "a" * 64, "source_content_version": 2,
        "original_text": "untrusted source",
    }
    translation = _translation_task_document([chapter], {
        "schema_version": "1.0", "confirmed_mappings": [],
        "established_english_spellings": [],
    })
    assert "c000001" in translation and "untrusted source" in translation
    assert '"translated_title": "<translated title>"' in translation
    assert '"paragraphs_preserved": true' in translation
    assert "do not add fields" in translation

    source = {
        "chunk_ids": {10}, "source_sha256": "b" * 64,
        "memory_context_json": '{"entities":[]}', "roster_map": {},
        "thread_map": {}, "memory_targets": [], "marked": "[chunk 10]\nCurrent.",
    }
    codex = _codex_task_document(source, 1.0)
    assert '"source_chunk_ids": [\n          10' in codex
    assert "one record per distinct newly introduced entity" in codex


def test_codex_contract_requires_supplied_provenance(tmp_path):
    output = tmp_path / "output"; output.mkdir(); run_id = uuid.uuid4()
    source = {"source_sha256": "a" * 64, "chunk_ids": {10}, "roster_map": {},
              "thread_map": {}, "memory_targets": [],
              "content": "Lin Xuan entered the mountain gate."}
    extraction = {"schema_version": "2.0", "chapter": 1.0, "source_sha256": "a" * 64,
        "mentions": [{"entity_ref": "m1", "surface_form": "Lin Xuan", "type": "character"}],
        "facts": [{"entity_ref": "m1", "fact_type": "action", "content": "Entered.", "source_chunk_ids": [10]}],
        "relationships": [], "events": [], "identity_reveals": [], "new_aliases": [],
        "state_changes": [], "relationship_state_changes": [], "thread_updates": [],
        "memory_updates": [], "warnings": []}
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

    extraction["facts"][0]["source_chunk_ids"] = [10]
    extraction["mentions"][0]["surface_form"] = "Lin Xuan's father"
    content = json.dumps(extraction).encode(); (output / "extraction.json").write_bytes(content)
    manifest = json.loads((output / "manifest.json").read_text())
    manifest["artifacts"][0].update(
        bytes=len(content), sha256=hashlib.sha256(content).hexdigest()
    )
    (output / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(AgyValidationError, match="does not occur literally"):
        validate_extraction_output(tmp_path, run_id, 1.0, source)


@pytest.mark.asyncio
async def test_codex_commit_is_idempotent_by_run_and_source_hash(workload_db):
    novel = workload_db["novel_id"]
    async with workload_db["pool"].acquire() as conn:
        await conn.execute("UPDATE chapters SET content='English chapter',original_text=NULL WHERE novel_id=$1 AND number=1;", novel)
        await conn.execute("INSERT INTO chunks (novel_id,chapter,chunk_index,text) VALUES ($1,1,0,'English chapter');", novel)
    run_id = uuid.uuid4(); digest = chapter_source_sha256("English chapter")
    empty = {key: [] for key in (
        "mentions", "facts", "relationships", "events", "identity_reveals", "new_aliases",
        "state_changes", "relationship_state_changes", "thread_updates", "memory_updates",
    )}
    result = await commit_extraction_proposal(
        novel, 1.0, empty,
        "Story begins.", expected_source_hash=digest, resolved_refs={}, run_id=run_id,
        model_label="agy:fake",
    )
    replay = await commit_extraction_proposal(
        novel, 1.0, empty,
        "Story begins.", expected_source_hash=digest, resolved_refs={}, run_id=run_id,
        model_label="agy:fake",
    )
    assert result["idempotent"] is False and replay["idempotent"] is True


@pytest.mark.asyncio
async def test_codex_v2_commit_atomically_persists_temporal_and_hierarchical_memory(workload_db):
    pool, novel = workload_db["pool"], workload_db["novel_id"]
    content = "Klein stays in Tingen while the Antigonus mystery remains unresolved."
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE chapters SET content=$2,original_text=NULL,part_label='Volume 1' "
            "WHERE novel_id=$1 AND number=1;",
            novel, content,
        )
        chunk_id = await conn.fetchval(
            "INSERT INTO chunks (novel_id,chapter,chunk_index,text) VALUES ($1,1,0,$2) RETURNING id;",
            novel, content,
        )
        klein = await conn.fetchval(
            "INSERT INTO entities (novel_id,canonical_name,type,first_seen_chapter) "
            "VALUES ($1,'Klein','character',0) RETURNING id;",
            novel,
        )
        tingen = await conn.fetchval(
            "INSERT INTO entities (novel_id,canonical_name,type,first_seen_chapter) "
            "VALUES ($1,'Tingen','location',0) RETURNING id;",
            novel,
        )
    data = {
        "mentions": [],
        "facts": [{"entity_ref": "e1", "fact_type": "location", "content": "Klein stays in Tingen.",
                   "source_chunk_ids": [chunk_id]}],
        "relationships": [], "events": [], "identity_reveals": [],
        "new_aliases": [{
            "entity_ref": "e1", "alias": "The Fool", "is_reveal": False,
            "source_chunk_ids": [chunk_id],
        }],
        "state_changes": [{
            "entity_ref": "e1", "state_key": "last_known_location", "operation": "set",
            "value": "Tingen", "value_entity_ref": "e2", "certainty": "confirmed",
            "narrative_scope": "current", "source_chunk_ids": [chunk_id],
        }],
        "relationship_state_changes": [{
            "source_ref": "e1", "target_ref": "e2", "state_key": "status",
            "operation": "set", "value": "present in", "certainty": "confirmed",
            "source_chunk_ids": [chunk_id],
        }],
        "thread_updates": [{
            "thread_ref": "p1", "title": "Antigonus mystery", "operation": "open",
            "summary": "The Antigonus mystery remains unresolved.", "participant_refs": ["e1"],
            "keywords": ["Antigonus"], "certainty": "confirmed", "source_chunk_ids": [chunk_id],
        }],
        "memory_updates": [{
            "kind": "checkpoint", "summary": "Klein remains in Tingen while investigating Antigonus.",
            "evidence_chunk_ids": [chunk_id],
        }, {
            "kind": "volume", "summary": "Klein begins investigating the Antigonus mystery in Tingen.",
            "evidence_chunk_ids": [chunk_id],
        }],
    }
    digest = chapter_source_sha256(content)
    result = await commit_extraction_proposal(
        novel, 1.0, data, "Klein remains in Tingen and the Antigonus mystery stays open.",
        expected_source_hash=digest, resolved_refs={}, roster_refs={"e1": klein, "e2": tingen},
        memory_targets=[
            {"kind": "checkpoint", "start_chapter": 1.0, "end_chapter": 1.0,
             "through_chapter": 1.0, "part_label": "Volume 1"},
            {"kind": "volume", "start_chapter": 1.0, "end_chapter": 1.0,
             "through_chapter": 1.0, "part_label": "Volume 1"},
        ],
        run_id=uuid.uuid4(), model_label="agy:fake",
    )
    assert result["idempotent"] is False
    async with pool.acquire() as conn:
        state = await current_entity_state(conn, novel, [klein], 1.0)
        counts = await conn.fetchrow(
            """
            SELECT
              (SELECT count(*) FROM chapter_summaries WHERE novel_id=$1) summaries,
              (SELECT count(*) FROM memory_segments WHERE novel_id=$1) memories,
              (SELECT count(*) FROM plot_thread_updates WHERE novel_id=$1) threads,
              (SELECT count(*) FROM relationship_state_transitions WHERE novel_id=$1) rel_states;
            """,
            novel,
        )
        version = await conn.fetchval(
            "SELECT pipeline_version FROM extraction_state WHERE novel_id=$1 AND chapter=1;", novel
        )
        alias_chapter = await conn.fetchval(
            "SELECT revealed_at_chapter FROM entity_aliases WHERE entity_id=$1 AND alias='The Fool';",
            klein,
        )
        memories = await conn.fetch(
            "SELECT kind,source_hash,evidence FROM memory_segments WHERE novel_id=$1 ORDER BY kind;",
            novel,
        )
        relationship_state = await current_relationship_state(conn, novel, [klein], 1.0)
    assert state[klein]["last_known_location"]["value"]["entity"] == "Tingen"
    assert dict(counts) == {"summaries": 1, "memories": 2, "threads": 1, "rel_states": 1}
    assert float(alias_chapter) == 1.0
    by_kind = {row["kind"]: row for row in memories}
    volume_evidence = by_kind["volume"]["evidence"]
    if isinstance(volume_evidence, str):
        volume_evidence = json.loads(volume_evidence)
    assert volume_evidence["current_checkpoint_source_hash"] \
        == by_kind["checkpoint"]["source_hash"]
    assert relationship_state[0]["value"] == "present in"
    assert version == settings.CODEX_PIPELINE_VERSION

    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO relationship_state_transitions
              (novel_id,source_id,target_id,chapter,state_key,operation,certainty,
               source_chunk_ids,pipeline_version)
            VALUES ($1,$2,$3,1,'status','clear','confirmed',$4,$5);
            """,
            novel, klein, tingen, [chunk_id], settings.CODEX_PIPELINE_VERSION,
        )
        assert await current_relationship_state(conn, novel, [klein], 1.0) == []


@pytest.mark.asyncio
async def test_bounded_context_is_deterministic_and_uses_real_completed_volume_label(workload_db):
    pool, novel = workload_db["pool"], workload_db["novel_id"]
    content = "Klein returned to Tingen."
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE chapters SET content=$2,original_text=NULL,kind='chapter',part_label='Volume 1' "
            "WHERE novel_id=$1 AND number=1;",
            novel, content,
        )
        await conn.execute(
            "INSERT INTO chunks (novel_id,chapter,chunk_index,text) VALUES ($1,1,0,$2);",
            novel, content,
        )
        klein = await conn.fetchval(
            "INSERT INTO entities (novel_id,canonical_name,type,description,first_seen_chapter) "
            "VALUES ($1,'Klein','character','A reader-visible protagonist.',0) RETURNING id;",
            novel,
        )
        await conn.execute(
            "INSERT INTO entity_aliases (novel_id,entity_id,alias,revealed_at_chapter) "
            "VALUES ($1,$2,'Klein',0);",
            novel, klein,
        )
        tingen = await conn.fetchval(
            "INSERT INTO entities (novel_id,canonical_name,type,description,first_seen_chapter) "
            "VALUES ($1,'Tingen','location','A city.',0) RETURNING id;",
            novel,
        )
        benson = await conn.fetchval(
            "INSERT INTO entities (novel_id,canonical_name,type,description,first_seen_chapter) "
            "VALUES ($1,'Benson','character','Klein''s brother.',0) RETURNING id;",
            novel,
        )
        await conn.execute(
            "INSERT INTO relationships "
            "(novel_id,source_id,target_id,chapter,relation_type,directed,content) "
            "VALUES ($1,$2,$3,0,'family',FALSE,'Klein and Benson are brothers.');",
            novel, klein, benson,
        )
        thread_one = await conn.fetchval(
            "INSERT INTO plot_threads (novel_id,stable_title,introduced_at_chapter,pipeline_version) "
            "VALUES ($1,'Klein question',0,$2) RETURNING id;",
            novel, settings.CODEX_PIPELINE_VERSION,
        )
        thread_two = await conn.fetchval(
            "INSERT INTO plot_threads (novel_id,stable_title,introduced_at_chapter,pipeline_version) "
            "VALUES ($1,'Tingen question',0,$2) RETURNING id;",
            novel, settings.CODEX_PIPELINE_VERSION,
        )
        await conn.executemany(
            """
            INSERT INTO plot_thread_updates
              (novel_id,thread_id,chapter,operation,summary,participants,keywords,certainty,
               source_chunk_ids,pipeline_version)
            VALUES ($1,$2,0,'open',$3,$4,$5,'confirmed','{}',$6);
            """,
            [
                (novel, thread_one, "Klein's question remains open.", [klein], ["Klein"], settings.CODEX_PIPELINE_VERSION),
                (novel, thread_two, "Tingen's question remains open.", [tingen], ["Tingen"], settings.CODEX_PIPELINE_VERSION),
            ],
        )
        metadata = {"kind": "chapter", "part_label": "Volume 1", "narrative_part_chapters": [1.0]}
        first = await build_chapter_context(conn, novel, 1.0, content, metadata)
        second = await build_chapter_context(conn, novel, 1.0, content, metadata)
    assert first["context_sha256"] == second["context_sha256"]
    assert list(first["roster_map"].values()) == [klein, tingen, benson]
    assert [target["kind"] for target in first["memory_targets"]] == ["checkpoint", "volume"]
    assert first["memory_targets"][1]["part_label"] == "Volume 1"
    thread_participants = {
        item["title"]: item["participants"] for item in first["context"]["open_threads"]
    }
    assert thread_participants == {
        "Klein question": ["e1"],
        "Tingen question": ["e2"],
    }
    assert first["manifest"]["tokens"]["estimated_total"] <= settings.CODEX_CONTEXT_MAX_TOKENS


@pytest.mark.asyncio
async def test_entity_merge_rejects_cross_novel_ids(workload_db):
    pool, novel = workload_db["pool"], workload_db["novel_id"]
    async with pool.acquire() as conn:
        other_novel = await conn.fetchval(
            "INSERT INTO novels (title,owner_id,visibility) VALUES ('Other',$1,'private') RETURNING id;",
            workload_db["user"]["id"],
        )
        keep = await conn.fetchval(
            "INSERT INTO entities (novel_id,canonical_name,type,first_seen_chapter) "
            "VALUES ($1,'Keep','character',1) RETURNING id;",
            novel,
        )
        drop = await conn.fetchval(
            "INSERT INTO entities (novel_id,canonical_name,type,first_seen_chapter) "
            "VALUES ($1,'Drop','character',1) RETURNING id;",
            other_novel,
        )
        with pytest.raises(ValueError, match="both entities"):
            await merge_entities(novel, keep, drop, conn)
        assert await conn.fetchval(
            "SELECT count(*) FROM entities WHERE id=ANY($1::bigint[]);", [keep, drop]
        ) == 2


@pytest.mark.asyncio
async def test_non_narrative_chunk_cleanup_is_safe_and_requires_reset_for_dependencies(workload_db):
    pool, novel = workload_db["pool"], workload_db["novel_id"]
    content = "Publisher front matter."
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE chapters SET content=$2,original_text=NULL,kind='frontmatter' "
            "WHERE novel_id=$1 AND number=1;",
            novel, content,
        )
        await conn.execute(
            "INSERT INTO chunks (novel_id,chapter,chunk_index,text) VALUES ($1,1,0,$2);",
            novel, content,
        )

    class Reading:
        async def chapter_snapshot(self, _novel_id, _chapter):
            return {"title": "Front matter", "content": content, "kind": "frontmatter"}

    runtime = SimpleNamespace(reading=Reading())
    assert await chunk_chapter(novel, 1.0, runtime=runtime) == 0
    async with pool.acquire() as conn:
        assert await conn.fetchval(
            "SELECT count(*) FROM chunks WHERE novel_id=$1 AND chapter=1;", novel
        ) == 0
        await conn.execute(
            "INSERT INTO extraction_state (novel_id,chapter,pipeline_version) VALUES ($1,1,'1.0');",
            novel,
        )
    with pytest.raises(RuntimeError, match="reset-codex"):
        await chunk_chapter(novel, 1.0, runtime=runtime)


@pytest.mark.asyncio
async def test_mid_block_v2_start_fails_without_grounded_child_summaries(workload_db):
    pool, novel = workload_db["pool"], workload_db["novel_id"]
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE chapters SET content='First',original_text=NULL,kind='chapter' "
            "WHERE novel_id=$1 AND number=1;",
            novel,
        )
        await conn.execute(
            "INSERT INTO chapters (novel_id,number,title,content,kind) "
            "VALUES ($1,2,'Second','Second chapter','chapter');",
            novel,
        )
        with pytest.raises(RuntimeError, match="build v2 chronologically"):
            await build_chapter_context(
                conn, novel, 2.0, "Second chapter",
                {
                    "kind": "chapter", "part_label": None,
                    "narrative_part_chapters": [1.0, 2.0],
                },
            )


@pytest.mark.asyncio
async def test_deterministic_force_rechunk_preserves_chunk_ids_and_citations(workload_db):
    pool, novel = workload_db["pool"], workload_db["novel_id"]
    content = "English sentence one.\n\nEnglish sentence two."
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE chapters SET content=$2,original_text=NULL WHERE novel_id=$1 AND number=1;",
            novel, content,
        )

    class Reading:
        async def chapter_snapshot(self, novel_id, chapter):
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    "SELECT title,content FROM chapters WHERE novel_id=$1 AND number=$2;",
                    novel_id, chapter,
                )
            return dict(row) if row else None

    runtime = SimpleNamespace(reading=Reading())
    assert await chunk_chapter(novel, 1.0, force=True, runtime=runtime) > 0
    async with pool.acquire() as conn:
        original_ids = [int(row["id"]) for row in await conn.fetch(
            "SELECT id FROM chunks WHERE novel_id=$1 AND chapter=1 ORDER BY chunk_index;", novel,
        )]
        entity_id = await conn.fetchval(
            "INSERT INTO entities (novel_id,canonical_name,type,first_seen_chapter) "
            "VALUES ($1,'Witness','character',1) RETURNING id;", novel,
        )
        fact_id = await conn.fetchval(
            "INSERT INTO entity_facts (novel_id,entity_id,chapter,content,source_chunk_ids) "
            "VALUES ($1,$2,1,'Observed.', $3::bigint[]) RETURNING id;",
            novel, entity_id, original_ids,
        )
        await conn.execute(
            "INSERT INTO extraction_state (novel_id,chapter,running_summary,source_sha256) "
            "VALUES ($1,1,'Observed.',$2);",
            novel, chapter_source_sha256(content),
        )

    await chunk_chapter(novel, 1.0, force=True, runtime=runtime)
    async with pool.acquire() as conn:
        rebuilt_ids = [int(row["id"]) for row in await conn.fetch(
            "SELECT id FROM chunks WHERE novel_id=$1 AND chapter=1 ORDER BY chunk_index;", novel,
        )]
        cited = list(await conn.fetchval(
            "SELECT source_chunk_ids FROM entity_facts WHERE id=$1;", fact_id,
        ))
        await conn.execute(
            "UPDATE chapters SET content=$2 WHERE novel_id=$1 AND number=1;",
            novel, content + " Changed.",
        )
    assert rebuilt_ids == original_ids and cited == original_ids
    with pytest.raises(RuntimeError, match="invalidate the chapter extraction"):
        await chunk_chapter(novel, 1.0, force=True, runtime=runtime)


@pytest.mark.asyncio
async def test_agy_retry_finds_committed_chapters_through_run_port(workload_db):
    pool = workload_db["pool"]
    novel = workload_db["novel_id"]
    user = workload_db["user"]
    job_id, _created = await service.create_job(
        "codex_build",
        novel_id=novel,
        user_id=user["id"],
        options={"from_chapter": 1, "to_chapter": 1},
        execution_backend="agy",
        backend_requested="agy",
    )
    run_id = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO ai_execution_runs "
            "(id,job_id,user_id,novel_id,workload,backend,status) "
            "VALUES ($1,$2,$3,$4,'codex_extract','agy','completed');",
            run_id, job_id, user["id"], novel,
        )
        await conn.execute(
            "INSERT INTO extraction_state "
            "(novel_id,chapter,running_summary,run_id,source_sha256) "
            "VALUES ($1,1,'Checkpointed.',$2,$3);",
            novel, run_id, chapter_source_sha256(""),
        )

    class Runs:
        async def job_run_ids(self, requested_job_id, workloads):
            return await PostgresAgyWorkerStateRepository(pool).job_run_ids(
                requested_job_id, workloads
            )

    chapters = await _checkpointed_job_chapters(
        {"id": job_id, "novel_id": novel}, SimpleNamespace(runs=Runs())
    )
    assert chapters == {1.0}


@pytest.mark.asyncio
async def test_chapter_1200_context_stays_bounded_and_ignores_historical_fact_bloat(
    workload_db,
):
    """Exercise the real PostgreSQL context builder at long-webnovel scale.

    The synthetic chapter/volume layout mirrors the useful shape of Lord of the
    Mysteries.  Provider calls are intentionally absent: this test is about the
    deterministic packing, hierarchy, ceiling, and database-growth invariants.
    """
    pool, novel = workload_db["pool"], workload_db["novel_id"]
    pipeline = settings.CODEX_PIPELINE_VERSION
    current_text = (
        "Character0001 and Character0002 discuss the Ancient Riddle with "
        "Character0003, Character0004, and Character0005. FutureOnly is merely "
        "an injected future-name trap."
    )
    part_ends = [213, 482, 732, 946, 1150, 1266, 1353, 1434]

    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM chapters WHERE novel_id=$1;", novel)
        await conn.execute(
            """
            INSERT INTO chapters (novel_id,number,title,content,kind,part_label)
            SELECT $1,n,'Synthetic ' || n,
                   CASE WHEN n=1200 THEN $2 ELSE 'Synthetic chapter ' || n || '.' END,
                   'chapter',
                   CASE
                     WHEN n<=213 THEN 'Volume 1: Clown'
                     WHEN n<=482 THEN 'Volume 2: Faceless'
                     WHEN n<=732 THEN 'Volume 3: Traveler'
                     WHEN n<=946 THEN 'Volume 4: Undying'
                     WHEN n<=1150 THEN 'Volume 5: Red Priest'
                     WHEN n<=1266 THEN 'Volume 6: Lightseeker'
                     WHEN n<=1353 THEN 'Volume 7: The Hanged Man'
                     ELSE 'Volume 8: Fool'
                   END
            FROM generate_series(1,1434) n;
            """,
            novel, current_text,
        )
        await conn.execute(
            """
            INSERT INTO chapter_summaries
              (novel_id,chapter,summary,token_count,source_sha256,evidence_chunk_ids,
               pipeline_version,model_label)
            SELECT $1,n,'Grounded summary for synthetic chapter ' || n || '.',8,
                   repeat('a',64),'{}'::bigint[],$2,'synthetic'
            FROM generate_series(1,1199) n;
            """,
            novel, pipeline,
        )

        checkpoint_rows = []
        part_start = 1
        for part_number, part_end in enumerate(part_ends, 1):
            if part_start > 1199:
                break
            completed_end = min(part_end, 1199)
            block_start = part_start
            while block_start <= completed_end:
                block_end = min(block_start + 24, part_end)
                if block_end > completed_end:
                    break
                label = (
                    "Volume 7: The Hanged Man" if part_number == 7
                    else "Volume 8: Fool" if part_number == 8
                    else [
                        "Volume 1: Clown", "Volume 2: Faceless",
                        "Volume 3: Traveler", "Volume 4: Undying",
                        "Volume 5: Red Priest", "Volume 6: Lightseeker",
                    ][part_number - 1]
                )
                source_hash = hashlib.sha256(
                    f"checkpoint:{block_start}:{block_end}".encode()
                ).hexdigest()
                checkpoint_rows.append((
                    novel, "checkpoint", block_start, block_end, block_end, label,
                    f"Grounded checkpoint {block_start}-{block_end}.", 12,
                    source_hash, json.dumps({"synthetic": True}), pipeline, "synthetic",
                ))
                block_start = block_end + 1
            if part_end <= 1199:
                label = checkpoint_rows[-1][5]
                source_hash = hashlib.sha256(
                    f"volume:{part_start}:{part_end}".encode()
                ).hexdigest()
                checkpoint_rows.append((
                    novel, "volume", part_start, part_end, part_end, label,
                    f"Grounded volume {part_start}-{part_end}.", 12,
                    source_hash, json.dumps({"synthetic": True}), pipeline, "synthetic",
                ))
            part_start = part_end + 1
        await conn.executemany(
            """
            INSERT INTO memory_segments
              (novel_id,kind,start_chapter,end_chapter,through_chapter,part_label,
               summary,token_count,source_hash,evidence,pipeline_version,model_label)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10::jsonb,$11,$12);
            """,
            checkpoint_rows,
        )

        await conn.execute(
            """
            INSERT INTO entities
              (novel_id,canonical_name,type,description,first_seen_chapter)
            SELECT $1,'Character' || lpad(n::text,4,'0'),'character',
                   repeat('grounded identity ',8),greatest(1,n % 1100)
            FROM generate_series(1,500) n;
            """,
            novel,
        )
        future_id = await conn.fetchval(
            """
            INSERT INTO entities
              (novel_id,canonical_name,type,description,first_seen_chapter)
            VALUES ($1,'FutureOnly','character','Must remain invisible.',1300)
            RETURNING id;
            """,
            novel,
        )
        entity_ids = [int(row["id"]) for row in await conn.fetch(
            "SELECT id FROM entities WHERE novel_id=$1 AND canonical_name LIKE 'Character%' "
            "ORDER BY canonical_name;",
            novel,
        )]
        await conn.executemany(
            """
            INSERT INTO entity_activity
              (novel_id,entity_id,chapter,mention_count,claim_count,event_count,salience,
               source_chunk_ids,pipeline_version)
            VALUES ($1,$2,1199,1,1,0,2,'{}'::bigint[],$3);
            """,
            [(novel, entity_id, pipeline) for entity_id in entity_ids[:150]],
        )
        await conn.executemany(
            """
            INSERT INTO entity_state_transitions
              (novel_id,entity_id,chapter,state_key,operation,value,certainty,
               narrative_scope,source_chunk_ids,pipeline_version)
            VALUES ($1,$2,1198,'last_known_location','set',$3::jsonb,'confirmed',
                    'current','{}'::bigint[],$4);
            """,
            [
                (novel, entity_id, json.dumps({"place": f"District {index % 12}"}), pipeline)
                for index, entity_id in enumerate(entity_ids[:120])
            ],
        )
        await conn.executemany(
            """
            INSERT INTO relationships
              (novel_id,source_id,target_id,chapter,relation_type,directed,content)
            VALUES ($1,$2,$3,1190,'associate',TRUE,'Synthetic connection.');
            """,
            [
                (novel, entity_ids[index], entity_ids[150 + index])
                for index in range(100)
            ],
        )
        await conn.executemany(
            """
            INSERT INTO relationship_state_transitions
              (novel_id,source_id,target_id,chapter,state_key,operation,value,certainty,
               source_chunk_ids,pipeline_version)
            VALUES ($1,$2,$3,1198,'trust','set','"allied"'::jsonb,'confirmed',
                    '{}'::bigint[],$4);
            """,
            [
                (novel, entity_ids[index], entity_ids[index + 1], pipeline)
                for index in range(0, 100, 2)
            ],
        )
        thread_ids = []
        for index in range(20):
            thread_ids.append(await conn.fetchval(
                """
                INSERT INTO plot_threads
                  (novel_id,stable_title,introduced_at_chapter,pipeline_version)
                VALUES ($1,$2,900,$3) RETURNING id;
                """,
                novel, f"Ancient Riddle branch {index + 1}", pipeline,
            ))
        await conn.executemany(
            """
            INSERT INTO plot_thread_updates
              (novel_id,thread_id,chapter,operation,summary,participants,keywords,
               certainty,source_chunk_ids,pipeline_version)
            VALUES ($1,$2,1199,'advance',$3,$4,$5,'confirmed','{}'::bigint[],$6);
            """,
            [
                (
                    novel, thread_id, f"Grounded unresolved branch {index + 1}.",
                    [entity_ids[index]], ["Ancient Riddle"], pipeline,
                )
                for index, thread_id in enumerate(thread_ids)
            ],
        )

    snapshot = await PostgresReadingCodexGateway(pool).chapter_snapshot(novel, 1200.0)
    assert snapshot is not None
    started = time.monotonic()
    async with pool.acquire() as conn:
        first = await build_chapter_context(
            conn, novel, 1200.0, current_text, snapshot,
            chapter_input_text=f"[chunk 999999]\n{current_text}",
        )
    initial_seconds = time.monotonic() - started

    # Add a deliberately large irrelevant historical fact set. It remains
    # available for retrieval, but must not alter the extraction prompt.
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO entity_facts
              (novel_id,entity_id,chapter,fact_type,content,source_chunk_ids)
            SELECT $1,e.id,500,'legacy_noise',
                   'Irrelevant historical fact ' || g || ' for ' || e.canonical_name,
                   '{}'::bigint[]
            FROM entities e CROSS JOIN generate_series(1,40) g
            WHERE e.novel_id=$1 AND e.id<>$2;
            """,
            novel, future_id,
        )
        await conn.execute(
            """
            INSERT INTO entity_facts
              (novel_id,entity_id,chapter,fact_type,content,source_chunk_ids)
            SELECT $1,$2,700+g,'bounded_read','Recent relevant fact ' || g,
                   '{}'::bigint[]
            FROM generate_series(1,260) g;
            """,
            novel, entity_ids[0],
        )
        await conn.execute(
            """
            INSERT INTO entity_facts
              (novel_id,entity_id,chapter,fact_type,content,source_chunk_ids)
            SELECT $1,$2,1300+g,'future_trap','Future fact ' || g,'{}'::bigint[]
            FROM generate_series(1,20) g;
            """,
            novel, entity_ids[0],
        )
        historical_fact_count = await conn.fetchval(
            "SELECT count(*) FROM entity_facts WHERE novel_id=$1;", novel
        )
        second = await build_chapter_context(
            conn, novel, 1200.0, current_text, snapshot,
            chapter_input_text=f"[chunk 999999]\n{current_text}",
        )

    profile = await get_entity_profile(novel, entity_ids[0], 1200.0)
    timeline = await get_timeline(novel, entity_ids[0], 1200.0)
    listed = await list_entities(novel, 1200.0)

    assert historical_fact_count == 20_280
    assert first["context_sha256"] == second["context_sha256"]
    assert first["serialized"] == second["serialized"]
    assert len(first["roster_map"]) <= settings.CODEX_CONTEXT_MAX_ENTITIES == 80
    assert len(first["context"]["open_threads"]) == settings.CODEX_CONTEXT_MAX_THREADS == 10
    assert len(first["context"]["current_checkpoint_children"]) == 24
    assert first["manifest"]["checkpoint_child_chapters"] == [
        float(number) for number in range(1176, 1200)
    ]
    assert first["context"]["recent_chapter_summaries"] == []
    assert {
        (item["kind"], item["start_chapter"], item["end_chapter"])
        for item in first["context"]["completed_memory"]
    } == {
        ("volume", 947.0, 1150.0),
        ("checkpoint", 1151.0, 1175.0),
    }
    assert first["memory_targets"] == [{
        "kind": "checkpoint", "start_chapter": 1176.0,
        "end_chapter": 1200.0, "through_chapter": 1200.0,
        "part_label": "Volume 6: Lightseeker",
    }]
    assert future_id not in first["roster_map"].values()
    assert "FutureOnly" not in first["serialized"]
    tokens = first["manifest"]["tokens"]
    assert tokens["entity_identity"] <= settings.CODEX_CONTEXT_ENTITY_TOKENS
    assert tokens["entity_state"] <= settings.CODEX_CONTEXT_STATE_TOKENS
    assert tokens["threads"] <= settings.CODEX_CONTEXT_THREAD_TOKENS
    assert tokens["estimated_total"] <= settings.CODEX_CONTEXT_MAX_TOKENS
    assert profile is not None
    assert len(profile["facts"]) == settings.CODEX_READ_MAX_FACTS == 200
    assert [item["chapter"] for item in profile["facts"]] == sorted(
        item["chapter"] for item in profile["facts"]
    )
    assert all(item["chapter"] <= 1200 for item in profile["facts"])
    assert len(profile["open_threads"]) <= settings.CODEX_CONTEXT_MAX_THREADS
    assert len(timeline) == settings.CODEX_READ_MAX_TIMELINE_ITEMS == 250
    assert all(item["chapter"] <= 1200 for item in timeline)
    assert len(listed) == settings.CODEX_READ_MAX_ENTITIES == 200
    assert all(item["first_seen_chapter"] <= 1200 for item in listed)
    # This is diagnostic data, not a brittle performance gate; pytest -s exposes
    # it during an explicit scale qualification run.
    print(
        "codex-v2-scale",
        {
            "chapter": 1200,
            "historical_facts": historical_fact_count,
            "selected_entities": len(first["roster_map"]),
            "dropped_entities": len(first["manifest"]["dropped_entities"]),
            "context_tokens": first["token_count"],
            "estimated_total_tokens": tokens["estimated_total"],
            "build_seconds": round(initial_seconds, 3),
        },
    )
