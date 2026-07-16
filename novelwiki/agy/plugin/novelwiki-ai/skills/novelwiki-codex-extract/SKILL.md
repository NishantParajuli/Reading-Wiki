---
name: novelwiki-codex-extract
description: Extracts a spoiler-safe NovelWiki codex v2 proposal and grounded chapter summary from one isolated chapter. Use only for codex_extract.
---

# NovelWiki codex extraction

1. Read only `input/task.md`. It contains the schema, bounded spoiler-safe memory,
   chapter ceiling, source SHA-256, and current chapter chunks in one bounded tool turn. In
   `output/extraction.json`, copy `chapter` and `source_sha256` exactly from that task data.
2. Draft mentions, facts, relationships, events, identity reveals, aliases, state transitions,
   relationship-state transitions, and important plot-thread updates using the
   supplied schema. Give every material claim supplied current-chapter chunk provenance.
   Emit one `mentions` record per distinct newly introduced entity with a unique `m1`, `m2`,
   ... ref. Its `surface_form` must be an exact literal word-bounded span copied from the
   current chapter chunks. Never substitute an inferred role, kinship label, description, or
   normalized name (for example, do not write "the protagonist's father" unless those exact
   words occur). Do not emit mention records for supplied roster `e` refs; reference those refs
   directly in claims. Reuse supplied `t` refs for plot threads. A new durable thread uses a
   unique `p1`, `p2`, ... ref, operation `open`, and a stable title. Produce checkpoint/volume memory
   updates exactly for the targets supplied in the task; never infer a volume boundary.
3. Perform a second review against every chunk. Add missed supported claims; remove unsupported,
   duplicated, future, or unresolved claims.
4. Write `output/extraction.json`, a 150-250 token current-chapter-only summary in
   `output/running-summary.md`, and
   `output/audit.json` containing observable review counts/uncertainties (no hidden reasoning).
5. Stop. Do not re-read output or write `output/manifest.json`; the trusted stop hook creates
   it with roles `codex_extraction`, `running_summary`, and `codex_audit`.

Never emit arbitrary database IDs or refer to chapters/chunks not supplied. Do not use terminal,
browser, MCP, permission, scheduling, subagent, directory-listing, or outside-workspace tools.
