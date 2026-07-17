---
name: novelwiki-disambiguate
description: Resolves a batch of NovelWiki gray entity mentions only to supplied candidate refs or NEW. Use only for entity_disambiguation.
---

# NovelWiki entity disambiguation

Read `input/cases.json`. For every case, select exactly one supplied `candidate_ref` when the
chapter context clearly identifies it; otherwise select `NEW`. Never invent an ID. Write exactly
this shape to `output/decisions.json`, with one object per input case and no extra fields:

```json
{
  "schema_version": "1.0",
  "decisions": [
    {
      "case_ref": "d1",
      "decision": "candidate1",
      "confidence": "high",
      "evidence": "brief observable evidence"
    }
  ]
}
```

Replace the example refs with each input case and its selected candidate. `confidence` must be
exactly `low`, `medium`, or `high`. The selected candidate reference belongs in `decision`;
never write a `candidate_ref` field. Then stop. Do not re-read output or write
`output/manifest.json`; the trusted stop hook creates it with role `disambiguation`. Use brief
observable evidence, not hidden reasoning. Do not list directories or use any outside-workspace
or execution tool.
