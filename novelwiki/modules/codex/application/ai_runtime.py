"""Codex-owned ports for provider, AGY, and Work execution capabilities."""

from __future__ import annotations

_ai = None
_work = None


def configure_ai_runtime(ai, work) -> None:
    global _ai, _work
    _ai, _work = ai, work


def _configured_ai():
    if _ai is None:
        raise RuntimeError("Codex AI capabilities were not wired by the composition root")
    return _ai


class _WorkProxy:
    def __getattr__(self, name):
        if _work is None:
            raise RuntimeError("Codex Work capabilities were not wired by the composition root")
        return getattr(_work, name)


service = _WorkProxy()


def _forward(name):
    def call(*args, **kwargs):
        return getattr(_configured_ai(), name)(*args, **kwargs)
    call.__name__ = name
    return call


call_chat_completion = _forward("call_chat_completion")
get_embedding = _forward("get_embedding")
get_embeddings_batch = _forward("get_embeddings_batch")
rerank_passages = _forward("rerank_passages")
run_agy = _forward("run_agy")
create_run = _forward("create_run")
update_run = _forward("update_run")
workspace_relpath = _forward("workspace_relpath")
load_json = _forward("load_json")
read_text_artifact = _forward("read_text_artifact")
validate_output_manifest = _forward("validate_output_manifest")
add_input = _forward("add_input")
create_run_workspace = _forward("create_run_workspace")
seal_inputs = _forward("seal_inputs")
sha256_file = _forward("sha256_file")
write_json = _forward("write_json")
safe_error_summary = _forward("safe_error_summary")
is_database_error = _forward("is_database_error")
