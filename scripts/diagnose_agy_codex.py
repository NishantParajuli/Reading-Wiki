#!/usr/bin/env python3
"""Run one bounded AGY Codex extraction canary without committing to the DB."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import socket
import sys
import tempfile
import uuid
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from novelwiki.bootstrap.codex_worker import build_codex_runtime
from novelwiki.modules.ai_execution.adapters.outbound.agy.contracts import InputManifest
from novelwiki.modules.ai_execution.adapters.outbound.agy.preflight import run_preflight
from novelwiki.modules.ai_execution.adapters.outbound.agy.prompts import build_task_prompt
from novelwiki.modules.ai_execution.adapters.outbound.agy.runner import run_agy
from novelwiki.modules.ai_execution.adapters.outbound.agy.workspace import (
    add_input,
    cli_state_path,
    create_run_workspace,
    seal_inputs,
    write_json,
)
from novelwiki.modules.codex.adapters.outbound.agy import (
    _chapter_input,
    _codex_task_document,
    validate_extraction_output,
)
from novelwiki.platform.config import settings
from novelwiki.platform.database import close_db_pool


def _model_step_types(state: Path) -> dict[str, int]:
    counts: Counter[str] = Counter()
    pattern = "antigravity-cli/brain/*/.system_generated/logs/transcript_full.jsonl"
    for transcript in state.glob(pattern):
        for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("source") == "MODEL":
                counts[str(item.get("type"))] += 1
    return dict(sorted(counts.items()))


async def run(args: argparse.Namespace) -> dict:
    if "host.docker.internal" in settings.DATABASE_URL:
        try:
            socket.getaddrinfo("host.docker.internal", None)
        except socket.gaierror:
            settings.DATABASE_URL = settings.DATABASE_URL.replace(
                "host.docker.internal", "127.0.0.1"
            )
    work = Path(tempfile.mkdtemp(prefix="novelwiki-agy-codex-canary-"))
    settings.AGY_WORK_DIR = str(work)
    settings.AGY_MAX_MODEL_REQUESTS_PER_RUN = args.max_requests
    settings.AGY_MAX_EMPTY_PLANNER_RESPONSES = args.max_stalled_steps
    run_id = uuid.uuid4()
    root: Path | None = None
    result = None
    report: dict = {
        "status": "failed",
        "novel_id": args.novel_id,
        "chapter": args.chapter,
    }
    try:
        if not getattr(args, "skip_preflight", False):
            await run_preflight()
        runtime = build_codex_runtime()
        source = await _chapter_input(args.novel_id, args.chapter, runtime)
        root = create_run_workspace(1, str(run_id))
        schema = {
            "schema_version": "1.0",
            "required_groups": [
                "mentions", "facts", "relationships", "events",
                "identity_reveals", "new_aliases",
            ],
            "mention_rules": (
                "one unique m-ref per distinct new entity; roster e-refs are not mentions"
            ),
            "allowed_chunk_ids": sorted(source["chunk_ids"]),
            "source_sha256": source["source_sha256"],
        }
        inputs = [
            add_input(
                root, "task.md",
                _codex_task_document(source, args.chapter).encode(),
                role="codex_task_bundle",
                media_type="text/markdown; charset=utf-8",
            ),
            add_input(
                root, "schema.json", json.dumps(schema, indent=2).encode(),
                role="extraction_schema", media_type="application/json",
            ),
        ]
        manifest = InputManifest(
            run_id=str(run_id), job_id=1, workload="codex_extract",
            plugin_version=settings.AGY_PLUGIN_VERSION,
            model=settings.AGY_MODEL_CODEX, novel_ref="novel",
            chapter_ceiling=args.chapter, inputs=inputs,
            limits={"allowed_chunk_ids": sorted(source["chunk_ids"]), "max_items": 5000},
            created_at=datetime.now(UTC),
        )
        write_json(root / "input" / "manifest.json", manifest.model_dump(mode="json"))
        seal_inputs(root)
        result = await run_agy(
            root,
            prompt=build_task_prompt("codex_extract"),
            model=settings.AGY_MODEL_CODEX,
        )
        report["runner_metrics"] = result.metrics()
        data, summary = validate_extraction_output(
            root, run_id, args.chapter, source, runtime=runtime
        )
        report.update(
            status="passed",
            items={key: len(value) for key, value in data.items()},
            summary_chars=len(summary),
        )
    except Exception as exc:
        report.update(
            failure_code=getattr(exc, "code", type(exc).__name__),
            error=str(exc),
            metrics=getattr(exc, "metrics", {}),
        )
        if result is not None:
            report["runner_metrics"] = result.metrics()
    finally:
        if root is not None:
            report["model_step_types"] = _model_step_types(cli_state_path(root))
        await close_db_pool()
        if args.keep:
            report["retained_root"] = str(work)
        else:
            shutil.rmtree(work, ignore_errors=True)
    return report


async def run_selected(args: argparse.Namespace) -> dict:
    chapters = args.chapter or [1.0]
    if len(chapters) == 1:
        args.chapter = chapters[0]
        return await run(args)
    await run_preflight()
    reports = []
    for chapter in chapters:
        child = argparse.Namespace(**vars(args))
        child.chapter = chapter
        child.skip_preflight = True
        reports.append(await run(child))
    return {
        "status": "passed" if all(item["status"] == "passed" for item in reports) else "failed",
        "novel_id": args.novel_id,
        "chapters": reports,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--novel-id", type=int, required=True)
    parser.add_argument(
        "--chapter", type=float, action="append",
        help="chapter to test; repeat the flag to share one preflight across a range",
    )
    parser.add_argument("--max-requests", type=int, default=16)
    parser.add_argument("--max-stalled-steps", type=int, default=10)
    parser.add_argument("--keep", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run_selected(parse_args())), sort_keys=True))
