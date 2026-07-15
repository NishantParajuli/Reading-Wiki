---
name: novelwiki-codex-verify
description: Independently verifies and repairs one draft NovelWiki codex extraction against its supplied chapter. Use only for codex_verify.
---

# NovelWiki codex verification

Read only `input/task.md`; it contains the chapter chunks, roster, draft extraction, draft
summary, schema, exact chapter ceiling, and exact source SHA-256 in one bounded tool turn. Check
every draft claim against the chapter; remove unsupported/duplicate/future claims and add missed supported
facts, relationships, events, aliases, and identity reveals. Every material claim needs one or
more supplied chunk IDs. Keep exactly one mention per distinct new entity with a unique `m` ref;
do not create mentions for supplied roster `e` refs. Write corrected `output/extraction.json`, corrected
`output/running-summary.md`, and `output/audit.json` with observable change counts, then stop.
Do not re-read output or write `output/manifest.json`; the trusted stop hook creates it. Do not
use terminal, browser, MCP, permission, scheduling, subagent, directory-listing, or
outside-workspace tools.
