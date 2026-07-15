#!/usr/bin/env python3
"""Basic stop/repair check. The worker performs the complete validator after exit."""
import hashlib
import json
import os
import sys
from datetime import datetime, timezone


def _expected_artifacts(root, input_manifest):
    workload = input_manifest.get("workload")
    fixed = {
        "smoke_test": [
            ("smoke.txt", "smoke", "text/plain; charset=utf-8"),
        ],
        "codex_extract": [
            ("extraction.json", "codex_extraction", "application/json"),
            ("running-summary.md", "running_summary", "text/markdown; charset=utf-8"),
            ("audit.json", "codex_audit", "application/json"),
        ],
        "codex_verify": [
            ("extraction.json", "codex_extraction", "application/json"),
            ("running-summary.md", "running_summary", "text/markdown; charset=utf-8"),
            ("audit.json", "codex_audit", "application/json"),
        ],
        "entity_disambiguation": [
            ("decisions.json", "disambiguation", "application/json"),
        ],
    }
    if workload in fixed:
        return fixed[workload]
    if workload == "translate_batch":
        expected = []
        for ref in input_manifest.get("inputs", []):
            if ref.get("role") != "chapter_metadata":
                continue
            name = os.path.basename(str(ref.get("path") or ""))
            if not name.endswith(".meta.json"):
                return []
            chapter_ref = name[:-len(".meta.json")]
            expected.extend([
                (f"chapters/{chapter_ref}.translation.txt", "translation", "text/plain; charset=utf-8"),
                (f"chapters/{chapter_ref}.meta.json", "translation_meta", "application/json"),
            ])
        return expected
    return []


def finalize_manifest(root):
    """Trusted hook computes hashes so the agent never needs a terminal turn."""
    input_path = os.path.join(root, "input", "manifest.json")
    if not os.path.isfile(input_path) or os.path.islink(input_path):
        return False
    with open(input_path, "r", encoding="utf-8") as handle:
        input_manifest = json.load(handle)
    expected = _expected_artifacts(root, input_manifest)
    if not expected:
        return False
    output = os.path.join(root, "output")
    refs = []
    expected_paths = {path for path, _role, _media in expected}
    actual_paths = set()
    for base, _dirs, files in os.walk(output):
        for name in files:
            rel = os.path.relpath(os.path.join(base, name), output).replace(os.sep, "/")
            if rel not in {"manifest.json", ".hook-repair-count"}:
                actual_paths.add(rel)
    if actual_paths != expected_paths:
        return False
    for rel, role, media_type in expected:
        path = os.path.realpath(os.path.join(output, rel))
        if os.path.commonpath([output, path]) != output or not os.path.isfile(path) or os.path.islink(path):
            return False
        with open(path, "rb") as handle:
            data = handle.read()
        refs.append({
            "path": rel,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
            "media_type": media_type,
            "role": role,
        })
    manifest = {
        "schema_version": "1.0",
        "run_id": input_manifest.get("run_id"),
        "workload": input_manifest.get("workload"),
        "status": "complete",
        "artifacts": refs,
        "warnings": [],
        "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "failure_reason": None,
    }
    manifest_path = os.path.join(output, "manifest.json")
    temp_path = manifest_path + ".tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, manifest_path)
    return True


def _validate_translation_artifacts(root, input_manifest, artifacts_by_role):
    expected = {}
    for ref in input_manifest.get("inputs", []):
        if ref.get("role") != "chapter_metadata":
            continue
        path = os.path.realpath(os.path.join(root, "input", str(ref.get("path") or "")))
        if os.path.commonpath([os.path.join(root, "input"), path]) != os.path.join(root, "input"):
            return "a translation input metadata path is unsafe"
        try:
            with open(path, "r", encoding="utf-8") as handle:
                source = json.load(handle)
        except (OSError, ValueError):
            return "translation input metadata is unreadable"
        chapter_ref = source.get("chapter_ref")
        if not isinstance(chapter_ref, str) or not chapter_ref:
            return "translation input chapter_ref is invalid"
        expected[chapter_ref] = source

    metadata_paths = artifacts_by_role.get("translation_meta", [])
    translation_paths = artifacts_by_role.get("translation", [])
    if len(metadata_paths) != len(expected) or len(translation_paths) != len(expected):
        return "translation output count does not match the requested chapters"
    translation_names = {os.path.basename(path) for path in translation_paths}
    seen = set()
    required = {
        "schema_version", "chapter_ref", "source_sha256", "source_content_version",
        "translated_title", "translation_path", "new_terms", "self_review",
    }
    term_types = {
        "name", "place", "skill", "item", "term", "faction", "organization", "concept",
    }
    for path in metadata_paths:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                metadata = json.load(handle)
        except (OSError, ValueError):
            return "translation metadata is not valid JSON"
        if not isinstance(metadata, dict) or set(metadata) != required:
            return "translation metadata has missing or extra fields"
        chapter_ref = metadata.get("chapter_ref")
        source = expected.get(chapter_ref)
        if source is None or chapter_ref in seen:
            return "translation metadata has an unknown or duplicate chapter_ref"
        seen.add(chapter_ref)
        if metadata.get("schema_version") != "1.0":
            return "translation metadata schema_version is invalid"
        if (
            metadata.get("source_sha256") != source.get("source_sha256")
            or metadata.get("source_content_version") != source.get("source_content_version")
        ):
            return "translation metadata source snapshot does not match the input"
        title = metadata.get("translated_title")
        if not isinstance(title, str) or not title or len(title) > 500:
            return "translation metadata translated_title is invalid"
        translation_name = str(metadata.get("translation_path") or "")
        if translation_name != f"{chapter_ref}.translation.txt" or translation_name not in translation_names:
            return "translation metadata translation_path is invalid"
        terms = metadata.get("new_terms")
        if not isinstance(terms, list) or len(terms) > 2000:
            return "translation metadata new_terms is invalid"
        for term in terms:
            if not isinstance(term, dict) or set(term) != {"source_term", "translation", "term_type"}:
                return "a translation new_terms entry has missing or extra fields"
            if not all(isinstance(term.get(key), str) and term[key] for key in ("source_term", "translation")):
                return "a translation new_terms entry is invalid"
            if term.get("term_type") not in term_types:
                return "a translation new_terms term_type is invalid"
        review = metadata.get("self_review")
        review_fields = {"complete", "paragraphs_preserved", "glossary_checked"}
        if not isinstance(review, dict) or set(review) != review_fields:
            return "translation self_review has missing or extra fields"
        if any(review.get(field) is not True for field in review_fields):
            return "translation self_review did not pass"
    if seen != set(expected):
        return "not every requested chapter has translation metadata"
    return None


def validate(root):
    root = os.path.realpath(root)
    input_manifest_path = os.path.join(root, "input", "manifest.json")
    output = os.path.join(root, "output")
    manifest_path = os.path.join(output, "manifest.json")
    if not os.path.isfile(input_manifest_path) or os.path.islink(input_manifest_path):
        return "input/manifest.json is missing"
    if not os.path.isfile(manifest_path) or os.path.islink(manifest_path):
        return "output/manifest.json is missing"
    with open(input_manifest_path, "r", encoding="utf-8") as handle:
        input_manifest = json.load(handle)
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    required = {
        "schema_version", "run_id", "workload", "status", "artifacts", "warnings",
        "completed_at", "failure_reason",
    }
    if set(manifest) != required:
        return "the final manifest has missing or extra top-level fields"
    if manifest.get("schema_version") != "1.0":
        return "the final manifest schema_version is invalid"
    if manifest.get("run_id") != input_manifest.get("run_id"):
        return "the final manifest run_id does not match the input"
    if manifest.get("workload") != input_manifest.get("workload"):
        return "the final manifest workload does not match the input"
    if not isinstance(manifest.get("warnings"), list):
        return "the final manifest warnings field is invalid"
    if not isinstance(manifest.get("completed_at"), str) or not manifest["completed_at"]:
        return "the final manifest completed_at field is invalid"
    if manifest.get("failure_reason") is not None and not isinstance(manifest["failure_reason"], str):
        return "the final manifest failure_reason field is invalid"
    if manifest.get("status") != "complete" or not isinstance(manifest.get("artifacts"), list):
        return "the final manifest is not complete"
    artifacts_by_role = {}
    for ref in manifest["artifacts"]:
        if not isinstance(ref, dict) or set(ref) != {"path", "sha256", "bytes", "media_type", "role"}:
            return "an artifact reference has missing or extra fields"
        rel = ref.get("path", "")
        if not rel or os.path.isabs(rel) or ".." in rel.replace("\\", "/").split("/"):
            return "an artifact path is unsafe"
        digest = ref.get("sha256")
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            return "an artifact SHA-256 is invalid"
        if not isinstance(ref.get("bytes"), int) or ref["bytes"] < 0:
            return "an artifact byte size is invalid"
        if not isinstance(ref.get("media_type"), str) or not ref["media_type"]:
            return "an artifact media type is invalid"
        if not isinstance(ref.get("role"), str) or not ref["role"]:
            return "an artifact role is invalid"
        path = os.path.realpath(os.path.join(output, rel))
        if os.path.commonpath([output, path]) != output or not os.path.isfile(path) or os.path.islink(path):
            return "a listed artifact is missing or unsafe"
        with open(path, "rb") as handle:
            data = handle.read()
        if len(data) != ref.get("bytes") or hashlib.sha256(data).hexdigest() != ref.get("sha256"):
            return "a listed artifact size or hash is wrong"
        artifacts_by_role.setdefault(ref["role"], []).append(path)
    if input_manifest.get("workload") in {"codex_extract", "codex_verify"}:
        extraction_paths = artifacts_by_role.get("codex_extraction", [])
        if len(extraction_paths) != 1:
            return "codex output must list exactly one codex_extraction artifact"
        schema_path = os.path.join(root, "input", "schema.json")
        if not os.path.isfile(schema_path) or os.path.islink(schema_path):
            return "input/schema.json is missing or unsafe"
        with open(schema_path, "r", encoding="utf-8") as handle:
            schema = json.load(handle)
        with open(extraction_paths[0], "r", encoding="utf-8") as handle:
            extraction = json.load(handle)
        if not isinstance(extraction, dict):
            return "the codex extraction must be a JSON object"
        if extraction.get("chapter") != input_manifest.get("chapter_ceiling"):
            return "codex chapter must copy input/manifest.json chapter_ceiling exactly"
        if extraction.get("source_sha256") != schema.get("source_sha256"):
            return (
                "codex source_sha256 must copy input/schema.json source_sha256 exactly; "
                "do not use the chapter.md artifact hash from input/manifest.json"
            )
    if input_manifest.get("workload") == "translate_batch":
        error = _validate_translation_artifacts(root, input_manifest, artifacts_by_role)
        if error:
            return error
    return None


def main():
    try:
        payload = json.load(sys.stdin)
        roots = payload.get("workspacePaths") or []
        root = os.path.realpath(roots[0] if roots else os.getcwd())
        error = validate(root)
        if error and finalize_manifest(root):
            error = validate(root)
    except Exception as exc:
        root = os.path.realpath(os.getcwd())
        error = f"manifest validation failed: {type(exc).__name__}"
    counter = os.path.join(root, "output", ".hook-repair-count")
    if error and not os.path.exists(counter):
        os.makedirs(os.path.dirname(counter), exist_ok=True)
        with open(counter, "w", encoding="ascii") as handle:
            handle.write("1")
        print(json.dumps({"decision": "continue", "reason": f"NovelWiki output validation failed: {error}. Repair the contracted files and rewrite manifest.json last."}))
        return
    if not error:
        try:
            os.unlink(counter)
        except FileNotFoundError:
            pass
    print(json.dumps({"decision": "stop", "reason": error or "validated"}))


if __name__ == "__main__":
    main()
