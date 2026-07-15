---
name: novelwiki-smoke
description: Performs the explicit isolated NovelWiki AGY health smoke test with no story data. Use only for smoke_test.
---

# NovelWiki smoke test

Write exactly `READY` plus a newline to `output/smoke.txt`, then stop. Do not read, list, or
verify files and do not write `output/manifest.json`; the trusted stop hook creates it.
