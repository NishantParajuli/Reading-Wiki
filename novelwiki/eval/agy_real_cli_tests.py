from __future__ import annotations

import os
import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from novelwiki.agy import PLUGIN_SOURCE
from novelwiki.agy.contracts import InputManifest
from novelwiki.agy.preflight import run_preflight
from novelwiki.agy.runner import run_agy
from novelwiki.agy.validators import read_text_artifact, validate_output_manifest
from novelwiki.modules.ai_execution.adapters.outbound.agy.prompts import build_task_prompt
from novelwiki.modules.ai_execution.adapters.outbound.agy.validators import load_json
from novelwiki.modules.translation.adapters.outbound.agy import (
    _chapter_ref,
    _translation_task_document,
    validate_translation_output,
)
from novelwiki.modules.translation.adapters.outbound.runtime import source_sha256
from novelwiki.agy.workspace import (
    add_input,
    create_run_workspace,
    seal_inputs,
    tree_sha256,
    write_json,
)
from novelwiki.config.settings import settings


pytestmark = [
    pytest.mark.agy_real,
    pytest.mark.skipif(
        os.getenv("RUN_REAL_AGY_TESTS") != "1",
        reason="set RUN_REAL_AGY_TESTS=1 to consume one authenticated AGY smoke run",
    ),
]


@pytest.mark.asyncio
async def test_real_cli_completes_hooked_headless_write(tmp_path, monkeypatch):
    work = tmp_path / "agy-real"
    monkeypatch.setattr(settings, "AGY_WORK_DIR", str(work))
    monkeypatch.setattr(settings, "AGY_PLUGIN_SHA256", tree_sha256(PLUGIN_SOURCE))
    monkeypatch.setattr(settings, "AGY_PRINT_TIMEOUT_SECONDS", 180)
    monkeypatch.setattr(settings, "AGY_OUTER_TIMEOUT_GRACE_SECONDS", 10)
    monkeypatch.setattr(settings, "AGY_MAX_MODEL_REQUESTS_PER_RUN", 8)
    monkeypatch.setattr(settings, "AGY_MAX_EMPTY_PLANNER_RESPONSES", 10)
    monkeypatch.setattr(settings, "AGY_REQUIRED_LOADED_HOOKS", 2)

    preflight = await run_preflight()
    assert preflight.healthy and preflight.plugin_valid

    run_id = str(uuid.uuid4())
    root = create_run_workspace(1, run_id)
    inputs = [
        add_input(
            root,
            "smoke.txt",
            b"Write exactly READY followed by a newline.\n",
            role="smoke_input",
            media_type="text/plain; charset=utf-8",
        )
    ]
    manifest = InputManifest(
        run_id=run_id,
        job_id=1,
        workload="smoke_test",
        plugin_version=settings.AGY_PLUGIN_VERSION,
        model=settings.AGY_MODEL_TRANSLATE,
        novel_ref="none",
        inputs=inputs,
        limits={"output_bytes": 64},
        created_at=datetime.now(UTC),
    )
    write_json(root / "input" / "manifest.json", manifest.model_dump(mode="json"))
    seal_inputs(root)

    result = await run_agy(
        root,
        prompt=build_task_prompt("smoke_test"),
        model=settings.AGY_MODEL_TRANSLATE,
    )
    output_manifest, roles = validate_output_manifest(
        root, run_id=run_id, workload="smoke_test", expected_roles={"smoke": 1},
    )
    smoke_hash = next(
        item.sha256 for item in output_manifest.artifacts if item.role == "smoke"
    )
    assert read_text_artifact(
        roles["smoke"][0], expected_sha256=smoke_hash
    ).strip() == "READY"
    assert result.hooks_loaded >= 2
    assert result.model_requests <= 6
    assert result.sandbox_blocks == 0


@pytest.mark.asyncio
async def test_real_cli_completes_one_read_translation_bundle(tmp_path, monkeypatch):
    work = tmp_path / "agy-real-translation"
    monkeypatch.setattr(settings, "AGY_WORK_DIR", str(work))
    monkeypatch.setattr(settings, "AGY_PLUGIN_SHA256", tree_sha256(PLUGIN_SOURCE))
    monkeypatch.setattr(settings, "AGY_PRINT_TIMEOUT_SECONDS", 180)
    monkeypatch.setattr(settings, "AGY_OUTER_TIMEOUT_GRACE_SECONDS", 10)
    monkeypatch.setattr(settings, "AGY_MAX_MODEL_REQUESTS_PER_RUN", 10)
    monkeypatch.setattr(settings, "AGY_MAX_EMPTY_PLANNER_RESPONSES", 10)
    monkeypatch.setattr(settings, "AGY_REQUIRED_LOADED_HOOKS", 2)
    assert (await run_preflight()).healthy

    run_id = uuid.uuid4()
    root = create_run_workspace(2, str(run_id))
    source = "林轩走进山门。\n\n他说：“你好。”\n\n今天是新的一天。\n\n他开始了旅程。"
    staged = [{
        "number": 1.0, "title": "第一章", "original_text": source,
        "language": "zh", "source_sha256": source_sha256(source),
        "source_content_version": 1,
    }]
    glossary = {
        "schema_version": "1.0",
        "confirmed_mappings": [{
            "source_term": "林轩", "translation": "Lin Xuan",
            "term_type": "name", "locked": True,
        }],
        "established_english_spellings": [],
    }
    chapter_ref = _chapter_ref(1.0)
    metadata = {
        "chapter_ref": chapter_ref, "number": 1.0, "source_title": "第一章",
        "source_language": "zh", "source_path": f"{chapter_ref}.source.txt",
        "source_sha256": staged[0]["source_sha256"], "source_content_version": 1,
    }
    inputs = [
        add_input(
            root, "task.md", _translation_task_document(staged, glossary).encode(),
            role="translation_task_bundle", media_type="text/markdown; charset=utf-8",
        ),
        add_input(
            root, "glossary.json", json.dumps(glossary).encode(),
            role="translation_glossary", media_type="application/json",
        ),
        add_input(
            root, f"chapters/{chapter_ref}.source.txt", source.encode(),
            role="chapter_source", media_type="text/plain; charset=utf-8",
        ),
        add_input(
            root, f"chapters/{chapter_ref}.meta.json", json.dumps(metadata).encode(),
            role="chapter_metadata", media_type="application/json",
        ),
    ]
    manifest = InputManifest(
        run_id=str(run_id), job_id=2, workload="translate_batch",
        plugin_version=settings.AGY_PLUGIN_VERSION, model=settings.AGY_MODEL_TRANSLATE,
        novel_ref="none", chapter_ceiling=1.0, inputs=inputs,
        limits={"chapters": 1}, created_at=datetime.now(UTC),
    )
    write_json(root / "input" / "manifest.json", manifest.model_dump(mode="json"))
    seal_inputs(root)
    result = await run_agy(
        root, prompt=build_task_prompt("translate_batch"),
        model=settings.AGY_MODEL_TRANSLATE,
    )
    runtime = SimpleNamespace(ai=SimpleNamespace(
        validate_output_manifest=validate_output_manifest,
        load_json=load_json,
        read_text_artifact=read_text_artifact,
    ))
    proposals = validate_translation_output(
        root, run_id, staged, glossary, runtime=runtime
    )
    assert proposals[0]["title"] and "Lin Xuan" in proposals[0]["translation"]
    assert result.hooks_loaded >= 2
    assert result.model_requests <= 8
