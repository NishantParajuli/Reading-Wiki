# Output contract

Read `input/manifest.json` first. Read only `input/`; write only documented files under
`output/`. Use UTF-8. Do not overwrite input or create undocumented files. Finish each
artifact before writing `output/manifest.json`; write that manifest last with exact byte
sizes and lowercase SHA-256 hashes. If completion is impossible, write a failed manifest
with a short machine-readable reason. Never fabricate missing work.

The final manifest is a strict contract. Copy `run_id` and `workload` exactly from the input
manifest, use an RFC 3339 UTC timestamp for `completed_at`, and emit every field shown here:

```json
{
  "schema_version": "1.0",
  "run_id": "<copy input run_id>",
  "workload": "<copy input workload>",
  "status": "complete",
  "artifacts": [
    {
      "path": "relative/path.txt",
      "sha256": "<64 lowercase hex characters>",
      "bytes": 1,
      "media_type": "text/plain; charset=utf-8",
      "role": "<contracted role>"
    }
  ],
  "warnings": [],
  "completed_at": "2026-01-01T00:00:00Z",
  "failure_reason": null
}
```

Do not add fields. A failed manifest uses `status: "failed"`, an empty artifact list, and a
short non-empty `failure_reason`; it still includes all other top-level fields.
