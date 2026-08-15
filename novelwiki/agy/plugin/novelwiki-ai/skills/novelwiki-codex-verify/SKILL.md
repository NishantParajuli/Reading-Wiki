---
name: novelwiki-codex-verify
description: Independently verifies and repairs one draft NovelWiki codex extraction against its supplied chapter. Use only for codex_verify.
---

# NovelWiki codex verification

Read only `input/task.md`; it contains the chapter chunks, bounded memory, draft extraction, draft
chapter summary, schema, exact chapter ceiling, and exact source SHA-256 in one bounded tool turn. Check
every draft claim against the chapter; remove unsupported/duplicate/future claims and add missed supported
facts, relationships, events, aliases, identity reveals, state changes, and important thread
updates. Recompute only the supplied checkpoint/volume targets, copying and partitioning all trusted
covered chapters into substantive key beats of no more than six chapters. Every material claim needs one or
more supplied chunk IDs and a short contiguous verbatim `evidence_text` span from one cited chunk.
Never stitch separated lines or omit intervening source words; for overlapping chunks, cite the
chunk containing the entire span. Accept useful paraphrases only when that evidence semantically
entails them. Repair or drop a claim when the anchor is absent, local to a different chunk, merely
shares vocabulary, or contradicts the passage. Keep
exactly one mention per distinct new entity with a unique `m` ref;
do not create mentions for supplied roster `e` refs. Every mention `surface_form` must be an
exact literal word-bounded span copied from the current chapter chunks, never an inferred role,
kinship label, description, or normalized name. When a newly spoken name belongs to a supplied
roster entity, keep it as that entity's alias instead of creating a duplicate mention. Every
cross-ref identity state must have the same pair in `identity_reveals`; those reveals may only link
supplied preexisting refs, since an identity introduced and revealed now is an alias. Explicitly name referenced
entities in claim text, reject off-topic thread drift, reconcile stale
transient state, and keep internal refs/chunk notation out of reader-facing text and the summary. Keep
the corrected current-chapter summary focused and substantive at 80-220 tokens.
Write corrected `output/extraction.json`, `output/running-summary.md`, and `output/audit.json` with
observable change counts, then stop.
Do not re-read output or write `output/manifest.json`; the trusted stop hook creates it. Do not
use terminal, browser, MCP, permission, scheduling, subagent, directory-listing, or
outside-workspace tools.
