# ADR 015: Codex-owned, authenticated chapter illustrations

Date: 2026-09-27

Status: accepted

## Context

Chapter art needs reusable character designs, access to story text, durable progress,
and a provider that returns image bytes. Existing imported assets are readable at novel
scope; generated art can reveal information from a particular chapter and therefore
needs the trusted reading ceiling. Existing Codex extraction/translation App Server
turns intentionally forbid tools and return strict structured data.

## Decision

- Codex owns art briefs, persistent reference sheets/scenes, source-validity checks, and
  the reader gallery. It receives chapter snapshots through Reading and backend/job
  capabilities through Bootstrap.
- Work owns the durable `codex_illustrate` job. AI Execution owns separate structured
  planning and native image sessions on the OpenAI Codex subscription worker. These
  jobs use the existing `codex_extract` grant and Codex enable switch, with explicit
  `gpt-6-luna`/`max` selection and no API fallback.
- Image generation is an explicit owner/admin action, bounded to one to three scenes
  and up to four new character sheets. Viewing art is free of provider calls and uses
  the same trusted progress boundary for every role.
- `codex_art` stores bounded PNG bytes in PostgreSQL. Authenticated image routes check
  novel access, chapter visibility, and source/reference freshness on each request.
  Generated art uses its own chapter-aware API instead of the novel-scoped imported-
  asset route.
- A persisted `codex_art_plans` row freezes the scene plan and reference revisions for
  retries; unique job slots checkpoint images. Each style publishes its newest complete
  scene batch. Shared chapter title/text hashes invalidate stale interpretations, and
  dependent scenes also validate their upstream character sheets.
- Native image sessions are a dedicated provider path. Translation and extraction keep
  their existing tool-free structured-output contract.

## Consequences

Database backups include generated image bytes and require corresponding capacity.
Transient rendering workspaces can be removed after each operation because the durable
plan and validated image checkpoints live in PostgreSQL. Reference reuse preserves
chosen visual identity across chapters without admitting later designs into earlier
scenes. Generated appearance choices remain distinct from canonical Codex facts.

The feature relies on the connected account exposing Luna/MAX and native image
generation; normal subscription provider-wait and cancellation behavior applies.
The current source and permission contract is documented in the living
[illustration pipeline](../pipelines/chapter-illustrations.md).
