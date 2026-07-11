# ADR 002: Baseline defect decisions before architecture migration

- Status: accepted
- Date: 2026-07-11
- Baseline: `c244a1f`

The defects identified by the migration audit are not architectural invariants. The decisions are:

| Defect | Decision |
|---|---|
| Generic-job refund crash window | Fix first with transaction-bound Work + Identity settlement and failure-injection coverage. |
| Auto-Codex scheduling refund gap | Fix first: a failed/deduplicated schedule releases the speculative reservation. |
| Incomplete source-offset Codex guard | Fix first by checking every chapter-keyed Codex artifact, not only chunks. |
| Novel deletion leaves audio/BM25 files | Preserve during migration; track cleanup as a separate product/storage change. |
| Ownerless `add-novel` CLI records | Preserve as intentional `SystemPrincipal` behavior. |
| `ALL_TABLES` omits `auth_rate_limits` | Preserve reset behavior during migration; correct only in a separately reviewed schema/reset change. |

Fix-first items must be isolated in behavior commits/PRs before their affected architectural slice.
Contract snapshots are regenerated after an approved fix. The migration itself does not silently
change any of the preserved behaviors.
