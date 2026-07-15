---
name: novelwiki-codex-extract
description: Extracts a spoiler-safe NovelWiki codex proposal and running summary from one isolated chapter. Use only for codex_extract.
---

# NovelWiki codex extraction

1. Read only `input/task.md`. It contains the schema, prior running summary, entity roster,
   chapter ceiling, source SHA-256, and current chapter chunks in one bounded tool turn. In
   `output/extraction.json`, copy `chapter` and `source_sha256` exactly from that task data.
2. Draft mentions, facts, relationships, events, identity reveals, and aliases using the
   supplied schema. Give every material claim supplied current-chapter chunk provenance.
   Emit one `mentions` record per distinct newly introduced entity with a unique `m1`, `m2`,
   ... ref. Do not emit mention records for supplied roster `e` refs; reference those refs
   directly in claims.
3. Perform a second review against every chunk. Add missed supported claims; remove unsupported,
   duplicated, future, or unresolved claims.
4. Write `output/extraction.json`, an updated `output/running-summary.md`, and
   `output/audit.json` containing observable review counts/uncertainties (no hidden reasoning).
5. Stop. Do not re-read output or write `output/manifest.json`; the trusted stop hook creates
   it with roles `codex_extraction`, `running_summary`, and `codex_audit`.

Never emit arbitrary database IDs or refer to chapters/chunks not supplied. Do not use terminal,
browser, MCP, permission, scheduling, subagent, directory-listing, or outside-workspace tools.
