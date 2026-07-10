#!/usr/bin/env python3
"""Basic stop/repair check. The worker performs the complete validator after exit."""
import hashlib
import json
import os
import sys


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
    return None


def main():
    try:
        payload = json.load(sys.stdin)
        roots = payload.get("workspacePaths") or []
        root = os.path.realpath(roots[0] if roots else os.getcwd())
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
