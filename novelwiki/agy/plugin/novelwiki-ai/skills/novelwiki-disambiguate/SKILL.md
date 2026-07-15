---
name: novelwiki-disambiguate
description: Resolves a batch of NovelWiki gray entity mentions only to supplied candidate refs or NEW. Use only for entity_disambiguation.
---

# NovelWiki entity disambiguation

Read `input/cases.json`. For every case, select exactly one supplied `candidate_ref` when the
chapter context clearly identifies it; otherwise select `NEW`. Never invent an ID. Write
`output/decisions.json`, then stop. Do not re-read output or write `output/manifest.json`; the
trusted stop hook creates it with role `disambiguation`. Use brief observable evidence, not
hidden reasoning. Do not list directories or use any outside-workspace or execution tool.
