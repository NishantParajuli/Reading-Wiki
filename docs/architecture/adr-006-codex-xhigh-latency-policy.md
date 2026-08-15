# ADR 006: OpenAI Codex uses Luna at xhigh effort

Status: Accepted — 2026-08-03

## Context

ADR 005 selected Luna at max effort with a separate verifier for the first long-book quality
qualification. A real chapter-5 extraction and independent verification took approximately
15 minutes in total. At that observed rate, a sequential 200-chapter continuation would take
about 50 hours. The deterministic quality contract already rejects ungrounded provenance,
generic or duplicate entities, incorrect reference attachment, invalid summaries, stale thread
updates, and incomplete hierarchical memory before any atomic commit.

## Decision

OpenAI Codex extraction, verification, disambiguation, and smoke workloads use
`gpt-5.6-luna` at `xhigh` effort. Translation continues to use `gpt-5.6-terra` at `xhigh`.
Application configuration rejects weaker effort for either model family. The independent
per-chapter verifier remains enabled, and every deterministic schema, provenance, citation,
identity, memory, temporal-state, and atomic-commit gate from pipeline 2.1 remains unchanged.
OpenAI contract version 1.3.2 records this execution-policy change.

## Consequences and trade-offs

- Long-book builds should use less reasoning capacity and wall time than the max-effort profile.
- The change does not reduce output coverage requirements or weaken host validation.
- A model-dependent quality difference remains possible, so xhigh must be qualified through the
  same chronological production canaries and checkpoint audits rather than inferred from effort
  labels alone.
- ADR 005 remains the historical record of the initial max-effort qualification profile; this ADR
  supersedes only its OpenAI Codex reasoning-effort decision.
