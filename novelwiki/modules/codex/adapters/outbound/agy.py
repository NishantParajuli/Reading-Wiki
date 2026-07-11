from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from novelwiki.platform.observability import audit as audit_log
from novelwiki.modules.ai_execution.public import DisambiguationPayload, ExtractionPayload, InputManifest
from novelwiki.modules.ai_execution.public import AgyCanceled, AgyValidationError, is_database_error, safe_error_summary
from novelwiki.modules.ai_execution.public import PreflightResult
from novelwiki.modules.ai_execution.public import run_agy
from novelwiki.modules.ai_execution.public import create_run, update_run, workspace_relpath
from novelwiki.modules.ai_execution.public import load_json, read_text_artifact, validate_output_manifest
from novelwiki.modules.ai_execution.public import add_input, create_run_workspace, seal_inputs, sha256_file, write_json
from novelwiki.platform.config import settings
from novelwiki.platform.database import get_db_pool
from novelwiki.modules.codex.adapters.outbound.ingest.extract import (
    chapter_source_sha256,
    commit_extraction_proposal,
    get_running_summary,
)
from novelwiki.modules.codex.adapters.outbound.ingest.link import find_resolution_candidates
from novelwiki.modules.work.public import service


ENTITY_TYPES = {"character", "location", "faction", "item", "concept", "organization"}
_LOCAL_REF_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_.:-]{0,79}$")


async def _chapters(job: dict) -> list[float]:
    opts = job.get("options") or {}
    from novelwiki.bootstrap.reading_migration import build_reading_codex_gateway
    novel_id = int(job["novel_id"])
    numbers = await (await build_reading_codex_gateway()).chapter_numbers(
        novel_id, opts.get("from_chapter"), opts.get("to_chapter"), True
    )
    if opts.get("force") or not numbers:
        return numbers
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT chapter FROM extraction_state WHERE novel_id=$1 "
            "AND chapter=ANY($2::numeric[]);", novel_id, numbers,
        )
    completed = {float(row["chapter"]) for row in rows}
    return [number for number in numbers if number not in completed]


async def _chapter_input(novel_id: int, chapter_number: float) -> dict:
    from novelwiki.bootstrap.reading_migration import build_reading_codex_gateway
    chapter = await (await build_reading_codex_gateway()).chapter_snapshot(
        novel_id, chapter_number
    )
    if not chapter or not chapter["content"]:
        raise RuntimeError("chapter source is missing")
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        chunks = await conn.fetch(
            "SELECT id,chunk_index,text FROM chunks WHERE novel_id=$1 AND chapter=$2 ORDER BY chunk_index;",
            novel_id, chapter_number,
        )
        if not chunks:
            raise RuntimeError("codex AGY extraction requires precomputed chunks for provenance")
        previous = await get_running_summary(novel_id, chapter_number, conn)
        entities = await conn.fetch(
            """
            SELECT e.id,e.canonical_name,e.type,e.first_seen_chapter,
                   COALESCE(d.description,e.description,'') AS description,
                   COALESCE(array_agg(DISTINCT a.alias) FILTER (WHERE a.alias IS NOT NULL),'{}') AS aliases
            FROM entities e
            LEFT JOIN LATERAL (
              SELECT description FROM entity_descriptions
              WHERE entity_id=e.id AND chapter < $2 ORDER BY chapter DESC LIMIT 1
            ) d ON TRUE
            LEFT JOIN entity_aliases a ON a.entity_id=e.id AND a.revealed_at_chapter < $2
            WHERE e.novel_id=$1 AND e.first_seen_chapter < $2
            GROUP BY e.id,d.description ORDER BY e.id;
            """,
            novel_id, chapter_number,
        )
    roster = {"ceiling": chapter_number - 0.000001, "entities": []}
    roster_map = {}
    for index, row in enumerate(entities[:2000], 1):
        ref = f"e{index}"
        roster_map[ref] = int(row["id"])
        roster["entities"].append({
            "entity_ref": ref, "canonical_name": row["canonical_name"], "type": row["type"],
            "aliases": list(row["aliases"] or [])[:50], "first_seen_chapter": float(row["first_seen_chapter"]),
            "short_context": (row["description"] or "")[:500],
        })
    marked = "\n\n".join(f"[chunk {int(row['id'])}]\n{row['text']}" for row in chunks)
    return {
        "title": chapter["title"] or f"Chapter {chapter_number}", "content": chapter["content"],
        "marked": marked, "source_sha256": chapter_source_sha256(chapter["content"]),
        "chunk_ids": {int(row["id"]) for row in chunks}, "previous_summary": previous,
        "roster": roster, "roster_map": roster_map,
    }


def _walk_strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)


def _claim_refs(item: dict) -> list[str]:
    refs = []
    for key in ("entity_ref", "source_ref", "target_ref", "persona_ref", "true_entity_ref", "location_ref"):
        if item.get(key):
            refs.append(str(item[key]))
    refs.extend(str(x) for x in (item.get("participant_refs") or []) if x)
    return refs


def validate_extraction_output(run_root: Path, run_id: uuid.UUID, chapter_number: float, source: dict,
                               *, workload: str = "codex_extract") -> tuple[dict, str]:
    manifest, roles = validate_output_manifest(
        run_root, run_id=str(run_id), workload=workload,
        expected_roles={"codex_extraction": 1, "running_summary": 1, "codex_audit": 1},
    )
    expected_hashes = {(run_root / "output" / ref.path).resolve(): ref.sha256 for ref in manifest.artifacts}
    try:
        extraction_path = roles["codex_extraction"][0]
        payload = ExtractionPayload.model_validate(
            load_json(extraction_path, expected_sha256=expected_hashes[extraction_path.resolve()])
        )
    except ValidationError as exc:
        raise AgyValidationError("codex extraction schema is invalid") from exc
    if float(payload.chapter) != float(chapter_number) or payload.source_sha256 != source["source_sha256"]:
        raise AgyValidationError("codex chapter/source snapshot mismatch")
    data = payload.model_dump(exclude={"schema_version", "chapter", "source_sha256", "warnings"})
    mentions = {}
    for mention in data["mentions"]:
        if not isinstance(mention, dict):
            raise AgyValidationError("mention must be an object")
        ref = str(mention.get("entity_ref") or "")
        surface = str(mention.get("surface_form") or "")
        if not _LOCAL_REF_RE.fullmatch(ref) or not surface or ref in mentions:
            raise AgyValidationError("mention ref/surface is missing, unsafe, or duplicated")
        if mention.get("type") not in ENTITY_TYPES:
            raise AgyValidationError("mention has an invalid entity type")
        mentions[ref] = mention
    allowed_refs = set(mentions) | set(source["roster_map"])
    material_groups = ("facts", "relationships", "events", "identity_reveals")
    for group in material_groups:
        for item in data[group]:
            if not isinstance(item, dict):
                raise AgyValidationError(f"{group} entries must be objects")
            ids = item.get("source_chunk_ids")
            if not isinstance(ids, list) or not ids:
                raise AgyValidationError(f"{group} entry lacks provenance")
            try:
                clean = {int(x) for x in ids}
            except (TypeError, ValueError) as exc:
                raise AgyValidationError("invalid chunk provenance") from exc
            if not clean.issubset(source["chunk_ids"]):
                raise AgyValidationError("claim cites an unsupplied chunk")
            if any(ref not in allowed_refs for ref in _claim_refs(item)):
                raise AgyValidationError("claim references an unresolved entity")
            if group == "facts" and (not item.get("entity_ref") or not item.get("content")):
                raise AgyValidationError("fact is missing its entity or content")
            if group == "relationships" and (not item.get("source_ref") or not item.get("target_ref")):
                raise AgyValidationError("relationship is missing an endpoint")
            if group == "events" and not item.get("description"):
                raise AgyValidationError("event is missing a description")
            if group == "identity_reveals" and (not item.get("persona_ref") or not item.get("true_entity_ref")):
                raise AgyValidationError("identity reveal is missing an endpoint")
    for alias in data["new_aliases"]:
        if not isinstance(alias, dict) or alias.get("entity_ref") not in allowed_refs or not alias.get("alias"):
            raise AgyValidationError("invalid alias proposal")
    if any(len(text) > 10_000 for text in _walk_strings(data)):
        raise AgyValidationError("codex output contains an oversized string")
    # Reject explicit future chapter fields wherever they occur.
    def check_future(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if str(key).lower() in {"database_id", "entity_id", "db_id"}:
                    raise AgyValidationError("codex proposal contains an unsupported database ID")
                if "chapter" in str(key).lower() and isinstance(child, (int, float)) and float(child) > chapter_number:
                    raise AgyValidationError("codex proposal references a future chapter")
                check_future(child)
        elif isinstance(value, list):
            for child in value:
                check_future(child)
    check_future(data)
    summary_path = roles["running_summary"][0]
    summary = read_text_artifact(summary_path, max_bytes=128_000,
                                 expected_sha256=expected_hashes[summary_path.resolve()]).strip()
    if not summary or len(summary) > 60_000:
        raise AgyValidationError("running summary is empty or too large")
    audit_path = roles["codex_audit"][0]
    audit = load_json(audit_path, max_bytes=1_000_000,
                      expected_sha256=expected_hashes[audit_path.resolve()])
    if not isinstance(audit, dict):
        raise AgyValidationError("codex audit must be an object")
    if {str(key).lower() for key in audit} & {"reasoning", "chain_of_thought", "thoughts", "hidden_reasoning"}:
        raise AgyValidationError("codex audit contains forbidden reasoning-trace fields")
    return data, summary


async def _run_separate_verification(job: dict, parent_run_id: uuid.UUID, source: dict,
                                     chapter_number: float, draft: dict, draft_summary: str,
                                     preflight: PreflightResult) -> tuple[dict, str, uuid.UUID, Path, object]:
    run_id = await create_run(
        job=job, workload="codex_verify", model=settings.AGY_MODEL_CODEX,
        runner_version=preflight.version, plugin_version=settings.AGY_PLUGIN_VERSION,
        plugin_sha256=preflight.plugin_sha256 or "", parent_run_id=parent_run_id,
    )
    root = create_run_workspace(int(job["id"]), str(run_id))
    inputs = [
        add_input(root, "chapter.md", source["marked"].encode(), role="chapter_source", media_type="text/markdown; charset=utf-8"),
        add_input(root, "entity-roster.json", json.dumps(source["roster"], ensure_ascii=False, indent=2).encode(), role="entity_roster", media_type="application/json"),
        add_input(root, "draft-extraction.json", json.dumps({"schema_version": "1.0", "chapter": chapter_number,
                  "source_sha256": source["source_sha256"], **draft, "warnings": []}, ensure_ascii=False, indent=2).encode(),
                  role="draft_extraction", media_type="application/json"),
        add_input(root, "draft-summary.md", draft_summary.encode(), role="draft_summary", media_type="text/markdown; charset=utf-8"),
        add_input(root, "schema.json", json.dumps({"allowed_chunk_ids": sorted(source["chunk_ids"]),
                  "source_sha256": source["source_sha256"]}, indent=2).encode(),
                  role="extraction_schema", media_type="application/json"),
    ]
    manifest = InputManifest(
        run_id=str(run_id), job_id=int(job["id"]), workload="codex_verify",
        plugin_version=settings.AGY_PLUGIN_VERSION, model=settings.AGY_MODEL_CODEX,
        novel_ref="novel", chapter_ceiling=chapter_number, inputs=inputs,
        limits={"allowed_chunk_ids": sorted(source["chunk_ids"])}, created_at=datetime.now(UTC),
    )
    write_json(root / "input" / "manifest.json", manifest.model_dump(mode="json")); seal_inputs(root)
    await update_run(run_id, status="running", input_sha256=sha256_file(root / "input" / "manifest.json"),
                     workspace_relpath=workspace_relpath(root), started_at=datetime.now(UTC))
    try:
        result = await run_agy(
            root, prompt=(
                "Run novelwiki-codex-verify for input/manifest.json. Copy chapter from "
                "chapter_ceiling and source_sha256 exactly from input/schema.json (never use "
                "the chapter.md artifact hash). Return a corrected complete extraction and "
                "summary with only supplied chunk provenance; write manifest.json last."
            ),
            model=settings.AGY_MODEL_CODEX,
            cancel_check=lambda: service.is_canceled(int(job["id"])),
            on_spawn=lambda pgid, started: update_run(run_id, process_group_id=pgid, process_started_at=started),
        )
        await update_run(run_id, status="validating", exit_code=result.exit_code)
        revised, summary = validate_extraction_output(root, run_id, chapter_number, source, workload="codex_verify")
        return revised, summary, run_id, root, result
    except Exception as exc:
        await update_run(run_id, status="canceled" if isinstance(exc, AgyCanceled) else "failed",
                         failure_code=getattr(exc, "code", "unknown"),
                         error_summary=safe_error_summary(exc), finished_at=datetime.now(UTC))
        raise


async def _run_disambiguation(
    job: dict, parent_run_id: uuid.UUID, cases: list[dict], preflight: PreflightResult,
) -> dict[str, int | None]:
    run_id = await create_run(
        job=job, workload="entity_disambiguation", model=settings.AGY_MODEL_CODEX,
        runner_version=preflight.version, plugin_version=settings.AGY_PLUGIN_VERSION,
        plugin_sha256=preflight.plugin_sha256 or "", parent_run_id=parent_run_id,
    )
    root = create_run_workspace(int(job["id"]), str(run_id))
    public_cases = []
    for case in cases:
        public_cases.append({**case, "candidates": [
            {key: value for key, value in candidate.items() if key != "entity_id"}
            for candidate in case["candidates"]
        ]})
    inputs = [add_input(root, "cases.json", json.dumps({"schema_version": "1.0", "cases": public_cases},
                                                        ensure_ascii=False, indent=2).encode(),
                        role="disambiguation_cases", media_type="application/json")]
    manifest = InputManifest(
        run_id=str(run_id), job_id=int(job["id"]), workload="entity_disambiguation",
        plugin_version=settings.AGY_PLUGIN_VERSION, model=settings.AGY_MODEL_CODEX,
        novel_ref="novel", inputs=inputs,
        limits={"cases": len(cases)}, created_at=datetime.now(UTC),
    )
    write_json(root / "input" / "manifest.json", manifest.model_dump(mode="json"))
    seal_inputs(root)
    await update_run(run_id, status="running", input_sha256=sha256_file(root / "input" / "manifest.json"),
                     workspace_relpath=workspace_relpath(root), started_at=datetime.now(UTC))
    try:
        result = await run_agy(
            root,
            prompt="Run novelwiki-disambiguate for input/manifest.json. Select only supplied candidate refs or NEW and write the contracted output manifest last.",
            model=settings.AGY_MODEL_CODEX,
            cancel_check=lambda: service.is_canceled(int(job["id"])),
            on_spawn=lambda pgid, started: update_run(run_id, process_group_id=pgid, process_started_at=started),
        )
        output_manifest, roles = validate_output_manifest(
            root, run_id=str(run_id), workload="entity_disambiguation",
            expected_roles={"disambiguation": 1},
        )
        try:
            decision_path = roles["disambiguation"][0]
            decision_hash = next(ref.sha256 for ref in output_manifest.artifacts if ref.role == "disambiguation")
            payload = DisambiguationPayload.model_validate(
                load_json(decision_path, expected_sha256=decision_hash)
            )
        except ValidationError as exc:
            raise AgyValidationError("invalid disambiguation artifact") from exc
        case_map = {case["case_ref"]: case for case in cases}
        if {d.case_ref for d in payload.decisions} != set(case_map) or len(payload.decisions) != len(cases):
            raise AgyValidationError("disambiguation cases are missing, duplicated, or extra")
        decisions = {}
        for decision in payload.decisions:
            case = case_map[decision.case_ref]
            candidates = {c["candidate_ref"]: int(c["entity_id"]) for c in case["candidates"]}
            if decision.decision == "NEW":
                decisions[case["mention_ref"]] = None
            elif decision.decision in candidates:
                decisions[case["mention_ref"]] = candidates[decision.decision]
            else:
                raise AgyValidationError("disambiguator selected an unsupplied candidate")
        await update_run(run_id, status="completed", output_sha256=sha256_file(root / "output" / "manifest.json"),
                         exit_code=result.exit_code, finished_at=datetime.now(UTC),
                         metrics={"cases": len(cases), "stdout_bytes": result.stdout_bytes,
                                  "stderr_bytes": result.stderr_bytes})
        return decisions
    except Exception as exc:
        await update_run(run_id, status="canceled" if isinstance(exc, AgyCanceled) else "failed",
                         failure_code=getattr(exc, "code", "unknown"),
                         error_summary=safe_error_summary(exc), finished_at=datetime.now(UTC))
        raise


async def _resolve_mentions(job: dict, parent_run_id: uuid.UUID, source: dict, data: dict,
                            chapter_number: float, preflight: PreflightResult) -> dict[str, int | None]:
    resolved, cases = {}, []
    pool = await get_db_pool()
    async with pool.acquire() as conn:
        for idx, mention in enumerate(data["mentions"], 1):
            ref = mention["entity_ref"]
            surface = mention["surface_form"]
            pos = source["content"].lower().find(surface.lower())
            context = source["content"][max(0, pos - 160):pos + len(surface) + 160] if pos >= 0 else surface
            proposal = await find_resolution_candidates(
                int(job["novel_id"]), surface, mention["type"], chapter_number, context,
                conn, description=mention.get("description"),
            )
            if proposal.existing_id is not None:
                resolved[ref] = proposal.existing_id
            elif proposal.candidates:
                cases.append({
                    "case_ref": f"d{idx}", "mention_ref": ref, "mention": surface,
                    "type": mention["type"], "local_context": context,
                    "candidates": [{"candidate_ref": f"candidate{candidate_index}", "entity_id": c["id"],
                                    "name": c["canonical_name"], "similarity": c["sim"]}
                                   for candidate_index, c in enumerate(proposal.candidates, 1)],
                })
            else:
                resolved[ref] = None
    if cases:
        try:
            resolved.update(await _run_disambiguation(job, parent_run_id, cases, preflight))
        except AgyCanceled:
            raise
        except Exception as exc:
            # A failed gray-case judge must never force a risky merge. Conservative
            # NEW preserves separation and lets an owner merge duplicates later.
            resolved.update({case["mention_ref"]: None for case in cases})
            await audit_log.record(
                "agy.disambiguation.fallback_new", user_id=job.get("user_id"),
                novel_id=job.get("novel_id"), data={"job_id": int(job["id"]),
                "cases": len(cases), "failure_code": getattr(exc, "code", "unknown")},
            )
    return resolved


async def _extract_chapter(job: dict, chapter_number: float, preflight: PreflightResult) -> None:
    source = await _chapter_input(int(job["novel_id"]), chapter_number)
    run_id = await create_run(
        job=job, workload="codex_extract", model=settings.AGY_MODEL_CODEX,
        runner_version=preflight.version, plugin_version=settings.AGY_PLUGIN_VERSION,
        plugin_sha256=preflight.plugin_sha256 or "",
    )
    root = create_run_workspace(int(job["id"]), str(run_id))
    inputs = [
        add_input(root, "chapter.md", source["marked"].encode(), role="chapter_source", media_type="text/markdown; charset=utf-8"),
        add_input(root, "running-summary.md", source["previous_summary"].encode(), role="running_summary", media_type="text/markdown; charset=utf-8"),
        add_input(root, "entity-roster.json", json.dumps(source["roster"], ensure_ascii=False, indent=2).encode(), role="entity_roster", media_type="application/json"),
        add_input(root, "schema.json", json.dumps({"schema_version": "1.0", "required_groups": [
            "mentions", "facts", "relationships", "events", "identity_reveals", "new_aliases"
        ], "allowed_chunk_ids": sorted(source["chunk_ids"]), "source_sha256": source["source_sha256"]}, indent=2).encode(),
                  role="extraction_schema", media_type="application/json"),
    ]
    manifest = InputManifest(
        run_id=str(run_id), job_id=int(job["id"]), workload="codex_extract",
        plugin_version=settings.AGY_PLUGIN_VERSION, model=settings.AGY_MODEL_CODEX,
        novel_ref="novel", chapter_ceiling=chapter_number, inputs=inputs,
        limits={"allowed_chunk_ids": sorted(source["chunk_ids"]), "max_items": 5000},
        created_at=datetime.now(UTC),
    )
    write_json(root / "input" / "manifest.json", manifest.model_dump(mode="json"))
    seal_inputs(root)
    await update_run(run_id, status="running", input_sha256=sha256_file(root / "input" / "manifest.json"),
                     workspace_relpath=workspace_relpath(root), started_at=datetime.now(UTC))
    artifacts_valid = False
    try:
        result = await run_agy(
            root,
            prompt=(
                "Run novelwiki-codex-extract for input/manifest.json. Copy chapter from "
                "chapter_ceiling and source_sha256 exactly from input/schema.json (never use "
                "the chapter.md artifact hash). Enforce supplied chunk provenance. Write only "
                "contracted output and manifest.json last."
            ),
            model=settings.AGY_MODEL_CODEX,
            cancel_check=lambda: service.is_canceled(int(job["id"])),
            on_spawn=lambda pgid, started: update_run(run_id, process_group_id=pgid, process_started_at=started),
        )
        await update_run(run_id, status="validating", exit_code=result.exit_code)
        data, summary = validate_extraction_output(root, run_id, chapter_number, source)
        artifacts_valid = True
        final_run_id, verify_root, verify_result = run_id, None, None
        if settings.AGY_SEPARATE_CODEX_VERIFY:
            data, summary, final_run_id, verify_root, verify_result = await _run_separate_verification(
                job, run_id, source, chapter_number, data, summary, preflight,
            )
        resolved = await _resolve_mentions(job, final_run_id, source, data, chapter_number, preflight)
        await commit_extraction_proposal(
            int(job["novel_id"]), chapter_number, data, summary,
            expected_source_hash=source["source_sha256"], resolved_refs=resolved,
            roster_refs=source["roster_map"], run_id=final_run_id,
            model_label=f"agy:{settings.AGY_MODEL_CODEX}",
            force=bool((job.get("options") or {}).get("force")),
        )
        await update_run(run_id, status="completed", output_sha256=sha256_file(root / "output" / "manifest.json"),
                         finished_at=datetime.now(UTC), metrics={
                             "chapter": chapter_number, "chunks": len(source["chunk_ids"]),
                             "items": sum(len(data[k]) for k in data),
                             "stdout_bytes": result.stdout_bytes, "stderr_bytes": result.stderr_bytes,
                         })
        if verify_root is not None:
            await update_run(final_run_id, status="completed",
                             output_sha256=sha256_file(verify_root / "output" / "manifest.json"),
                             finished_at=datetime.now(UTC), metrics={
                                 "chapter": chapter_number, "separate_verification": True,
                                 "stdout_bytes": verify_result.stdout_bytes,
                                 "stderr_bytes": verify_result.stderr_bytes,
                             })
    except Exception as exc:
        if artifacts_valid and is_database_error(exc):
            await update_run(run_id, status="validating", failure_code="database_commit_failed",
                             error_summary="database_commit_failed", finished_at=None)
        else:
            await update_run(run_id, status="canceled" if isinstance(exc, AgyCanceled) else "failed",
                             failure_code=getattr(exc, "code", "unknown"),
                             error_summary=safe_error_summary(exc), finished_at=datetime.now(UTC))
        raise


async def _resume_ready_commits(job: dict, preflight: PreflightResult) -> set[float]:
    """Use a complete extraction artifact after worker loss without rerunning extraction."""
    from novelwiki.bootstrap.ai_execution_worker import resumable_ai_runs
    rows = list(reversed(await resumable_ai_runs(
        int(job["id"]), ("codex_extract", "codex_verify")
    )))
    completed: set[float] = set()
    for row in rows:
        run_id = row["id"]
        root = Path(settings.AGY_WORK_DIR) / (row["workspace_relpath"] or "")
        try:
            if sha256_file(root / "input" / "manifest.json") != row["input_sha256"]:
                raise AgyValidationError("saved input manifest hash changed")
            manifest = load_json(root / "input" / "manifest.json")
            chapter = float(manifest["chapter_ceiling"])
            if chapter in completed:
                await update_run(run_id, status="completed", finished_at=datetime.now(UTC),
                                 metrics={"chapter": chapter, "superseded_by_resumed_verification": True})
                continue
            source = await _chapter_input(int(job["novel_id"]), chapter)
            data, summary = validate_extraction_output(
                root, run_id, chapter, source, workload=row["workload"],
            )
            resolved = await _resolve_mentions(job, run_id, source, data, chapter, preflight)
            await commit_extraction_proposal(
                int(job["novel_id"]), chapter, data, summary,
                expected_source_hash=source["source_sha256"], resolved_refs=resolved,
                roster_refs=source["roster_map"], run_id=run_id,
                model_label=f"agy:{settings.AGY_MODEL_CODEX}",
                force=bool((job.get("options") or {}).get("force")),
            )
            await update_run(run_id, status="completed",
                             output_sha256=sha256_file(root / "output" / "manifest.json"),
                             finished_at=datetime.now(UTC),
                             metrics={"chapter": chapter, "resumed_commit": True})
            if row["parent_run_id"]:
                await update_run(row["parent_run_id"], status="completed", finished_at=datetime.now(UTC),
                                 metrics={"chapter": chapter, "completed_via_verification_run": str(run_id)})
            completed.add(chapter)
        except Exception as exc:
            await update_run(run_id, status="worker_lost", failure_code="worker_lost",
                             error_summary=f"worker_lost: {type(exc).__name__}",
                             finished_at=datetime.now(UTC))
    return completed


async def execute_codex_job(job: dict, preflight: PreflightResult) -> dict:
    resumed = await _resume_ready_commits(job, preflight)
    chapters = [chapter for chapter in await _chapters(job) if chapter not in resumed]
    total = len(chapters)
    overall = len(resumed) + total
    await service.set_progress(int(job["id"]), {"step": 3, "steps": 4, "done": len(resumed),
                                                "total": overall, "resumed_commits": len(resumed)},
                               stage="waiting for AGY extraction")
    for index, chapter in enumerate(chapters, 1):
        if await service.is_canceled(int(job["id"])):
            raise AgyCanceled()
        await service.update_job(int(job["id"]), stage=f"extracting AGY chapter {index}/{total}")
        await _extract_chapter(job, chapter, preflight)
        await service.set_progress(int(job["id"]), {
            "step": 3, "steps": 4, "done": len(resumed) + index, "total": overall,
            "current_chapter": chapter, "resumed_commits": len(resumed),
        })
    return {"chapters": overall, "resumed_commits": len(resumed)}
