---
name: novelwiki-codex-extract
description: Extracts a spoiler-safe NovelWiki codex proposal and running summary from one isolated chapter. Use only for codex_extract.
---

# NovelWiki codex extraction

1. Read the manifest, schema, prior running summary, entity roster, and `chapter.md`.
2. Draft mentions, facts, relationships, events, identity reveals, and aliases using the
   supplied schema. Give every material claim supplied current-chapter chunk provenance.
3. Perform a second review against every chunk. Add missed supported claims; remove unsupported,
   duplicated, future, or unresolved claims.
4. Write `output/extraction.json`, an updated `output/running-summary.md`, and
   `output/audit.json` containing observable review counts/uncertainties (no hidden reasoning).
5. Write `output/manifest.json` last with roles `codex_extraction`, `running_summary`, and
   `codex_audit`.

Never emit arbitrary database IDs or refer to chapters/chunks not supplied. Do not use terminal,
browser, MCP, permission, scheduling, subagent, or outside-workspace tools.
