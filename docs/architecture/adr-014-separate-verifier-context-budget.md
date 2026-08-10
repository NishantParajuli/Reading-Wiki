# ADR-014: Give complete verification drafts separate context headroom

- Status: accepted
- Date: 2026-08-06

## Context

Chapter 257 is unusually long: its chunk-marked current text is 28,211 tokens and its trusted
bounded memory is 11,600 tokens. Primary extraction still fit at 42,131 tokens. Both successful
primary artifacts then failed before verification because adding their complete drafts produced
48,829- and 51,076-token tasks against the same 48,000-token cap. The second attempt could not fix
a deterministic transport-budget mismatch and generated an even larger valid draft.

Truncating the chapter, trusted memory, or extracted claims would undermine the quality purpose of
the independent verifier. Raising the primary cap would inflate normal extraction and weaken its
bounded-memory invariant.

## Decision

OpenAI Codex contract 1.3.10 keeps `CODEX_CONTEXT_MAX_TOKENS=48000` for primary extraction and adds
`CODEX_VERIFY_CONTEXT_MAX_TOKENS=64000` for verification. The verifier contains the same complete
bounded source and memory plus the complete primary proposal. Draft JSON uses compact separators to
remove formatting-only tokens; no field or item is dropped. The direct API verifier uses the same
separate cap.

Configuration requires the verifier cap to be at least the primary cap and no more than 128,000.
Tasks that exceed their applicable bound fail with `codex_context_budget_exceeded`, distinguishing
transport size from a malformed model artifact. Task construction occurs before a run record is
created, and every sealed manifest records the measured and maximum task-token counts.

## Consequences

- Both chapter-257 drafts fit at 47,156 and 48,751 tokens with more than 15k verifier headroom.
- Primary context selection, ordinary chapter cost, persisted RAG data, artifact schema 2.2, and
  pipeline-2.1 database rows are unchanged.
- Verification retains the full chapter, trusted context, extraction proposal, and targeted issues.
- A genuinely oversized verifier still fails closed under a documented hard bound.
- Already committed chapters remain valid; uncommitted older-contract work regenerates.
