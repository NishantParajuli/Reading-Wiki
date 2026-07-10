---
name: novelwiki-smoke
description: Performs the explicit isolated NovelWiki AGY health smoke test with no story data. Use only for smoke_test.
---

# NovelWiki smoke test

Read `input/manifest.json` and `input/smoke.txt`. Write exactly `READY` plus a newline to
`output/smoke.txt`. Then write `output/manifest.json` last, listing that file with role `smoke`,
its exact byte size, UTF-8 text media type, and lowercase SHA-256. Do nothing else.
