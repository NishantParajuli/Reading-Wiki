"""Dependencies used by Codex ingestion and dedicated execution adapters."""

from __future__ import annotations

from .ports import CodexReadingPort, ResumableAiRunPort

_reading: CodexReadingPort | None = None
_runs: ResumableAiRunPort | None = None


def configure_worker_dependencies(
    reading: CodexReadingPort, runs: ResumableAiRunPort
) -> None:
    global _reading, _runs
    _reading = reading
    _runs = runs


def reading_port() -> CodexReadingPort:
    if _reading is None:
        raise RuntimeError("Codex Reading port was not wired by the composition root")
    return _reading


def resumable_run_port() -> ResumableAiRunPort:
    if _runs is None:
        raise RuntimeError("Codex resumable-run port was not wired by the composition root")
    return _runs
