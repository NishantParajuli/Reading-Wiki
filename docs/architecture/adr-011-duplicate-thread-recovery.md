# ADR-011: Route bounded duplicate thread updates through verification

- Status: accepted
- Date: 2026-08-04

## Context

Codex chapters 49 and 70 each produced two independently grounded updates for one supplied plot
thread. The one-update-per-thread invariant is correct because the commit model persists one
ordered transition per thread and chapter. However, primary host validation rejected both drafts
before the configured independent verifier could combine the developments.

Automatically accepting every duplicate would make thread state ambiguous. Automatically dropping
all but one before review could also erase a meaningful development.

## Decision

OpenAI Codex contract 1.3.7 keeps artifact schema 2.2 and the final one-update-per-thread rule.
When separate verification is enabled, primary validation records every update after the first as
an exact duplicate repair issue and passes the complete draft plus those issues to the verifier.
This deferred graph check also permits a new local thread's `open` plus duplicate operation to reach
verification, provided the same proposal contains a valid titled `open` for that ref.

The verified artifact is checked again. If exactly one duplicate remains, the host retains the
first fully validated update and quarantines only the extra. If more than one extra remains, the
chapter fails with `thread_update_broad_failure` and retries. Single-pass paths remain strict and
reject duplicate updates immediately.

## Consequences

- The verifier can combine independently grounded developments without weakening the persisted
  plot-thread invariant.
- One verifier oversight no longer loses an otherwise valid chapter.
- Broad duplicate output is never silently reduced.
- Evidence locality, entity/ref alignment, topic grounding, dormant-thread reopening, and final
  reference-graph validation still apply to the retained update.
- Persisted schemas and existing pipeline-2.1 commits are unchanged.
