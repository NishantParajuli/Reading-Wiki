---
name: novelwiki-codex-verify
description: Independently verifies and repairs one draft NovelWiki codex extraction against its supplied chapter. Use only for codex_verify.
---

# NovelWiki codex verification

Read the manifest, chapter chunks, roster, draft extraction, draft summary, and schema. Copy
`chapter` from the manifest's `chapter_ceiling` and `source_sha256` exactly from
`input/schema.json`; never substitute the manifest's `chapter.md` artifact hash. Check every draft
claim against the chapter; remove unsupported/duplicate/future claims and add missed supported
facts, relationships, events, aliases, and identity reveals. Every material claim needs one or
more supplied chunk IDs. Write corrected `output/extraction.json`, corrected
`output/running-summary.md`, and `output/audit.json` with observable change counts. Write the final
manifest last with roles `codex_extraction`, `running_summary`, and `codex_audit`. Do not use
terminal, browser, MCP, permission, scheduling, subagent, or outside-workspace tools.
