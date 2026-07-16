---
name: novelwiki-codex-verify
description: Independently verifies and repairs one draft NovelWiki codex extraction against its supplied chapter. Use only for codex_verify.
---

# NovelWiki codex verification

Read only `input/task.md`; it contains the chapter chunks, bounded memory, draft extraction, draft
chapter summary, schema, exact chapter ceiling, and exact source SHA-256 in one bounded tool turn. Check
every draft claim against the chapter; remove unsupported/duplicate/future claims and add missed supported
facts, relationships, events, aliases, identity reveals, state changes, and important thread
updates. Recompute only the supplied checkpoint/volume targets. Every material claim needs one or
more supplied chunk IDs. Keep exactly one mention per distinct new entity with a unique `m` ref;
do not create mentions for supplied roster `e` refs. Every mention `surface_form` must be an
exact literal word-bounded span copied from the current chapter chunks, never an inferred role,
kinship label, description, or normalized name. Write corrected `output/extraction.json`, corrected
`output/running-summary.md`, and `output/audit.json` with observable change counts, then stop.
Do not re-read output or write `output/manifest.json`; the trusted stop hook creates it. Do not
use terminal, browser, MCP, permission, scheduling, subagent, directory-listing, or
outside-workspace tools.
