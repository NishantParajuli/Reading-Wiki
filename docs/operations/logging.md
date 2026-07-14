# Structured logging and Grafana/Loki operations

Tideglass emits application, HTTP, worker, job, and AGY lifecycle logs as one JSON object
per line on the process logging stream (standard error). Docker and journald capture that
stream, while CLI result output remains clean. The web container and dedicated host AGY worker use the
same schema, so Docker or journald can forward them to Loki without regex parsing.

The logging stream complements, rather than replaces, durable state:

- PostgreSQL job rows remain the source of truth for current status and progress.
- `audit_events` remains the durable, security-oriented record of selected actions.
- JSON logs provide detailed timing, retries, stack traces, worker identity, and the
  sequence around failures.

## Configuration

| Setting | Default | Effect |
|---|---|---|
| `LOG_FORMAT` | `json` | `json` for one object per line; `console` for interactive local output |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL` |
| `LOG_SERVICE` | `tideglass` | stable service field attached to every application log |
| `LOG_ENVIRONMENT` | `development` | deployment name such as `production`, `staging`, or `development` |
| `LOG_HTTP_REQUESTS` | `true` | emit one completion/failure event per HTTP request |
| `LOG_JOB_PROGRESS` | `true` | emit stage/progress transitions for durable jobs |

Keep `INFO` in normal production operation. `DEBUG` additionally exposes successful lease
heartbeats, AGY worker heartbeats, and maintenance sweeps; heartbeat failures are always
`WARNING` because they can lead to lease recovery.

Uvicorn access/error loggers are routed through the same formatter. The web process (which
hosts the generic, import, and narration workers), CLI processes, and dedicated
`python -m novelwiki.agy.worker` process all install the application logging configuration.

## Common fields

Every record contains `timestamp`, `level`, `event`, `message`, `logger`, `service`,
`environment`, `host`, process/thread identity, and source module/function/line. Relevant events
also include:

| Field | Meaning |
|---|---|
| `request_id` | incoming or generated `X-Request-ID` for HTTP and scheduling work |
| `job_system` | `generic`, `import`, `tts`, or `inline_background` |
| `job_id`, `job_kind` | durable row ID and real task name, such as `codex_build`, `import_pdf`, or `narrate_book` |
| `worker_type`, `worker_id` | worker role and per-process instance/lease identity |
| `user_id`, `novel_id` | numeric ownership/correlation IDs; names and email addresses are not added |
| `attempt`, `max_attempts` | current generic/AGY attempt and retry ceiling |
| `execution_backend`, `backend_model` | `api`/`agy` routing and selected model |
| `agy_workload`, `ai_run_id` | precise AGY task (`translate_batch`, `codex_extract`, and nested run workloads) and UUID |
| `status`, `stage`, `progress` | resulting durable state and structured progress object |
| `duration_ms` | elapsed wall-clock time for requests, attempts, subprocesses, or generated chapters |
| `error_type`, `error_message`, `stack_trace` | exception class, summary, and traceback when a live exception is logged |

`request_id` follows the synchronous HTTP action. A durable worker may execute minutes
later in another process, so `job_id` is the bridge between the scheduling request and all
later attempt logs. The `job.created` audit row retains the scheduling request ID.

## Event families

The high-value lifecycle events are:

- Generic Work: `job.created`, `job.deduplicated`, `job.started`, `job.progress`,
  `job.attempt_finished`, `job.retry_scheduled`, `job.failed`, `job.cancel_requested`,
  `job.lease_recovered`, and `quota.refunded`.
- Imports/OCR: `import_job.created`, `import_job.started`,
  `import_job.state_changed`, `import_job.parsed`,
  `import_job.awaiting_ocr_confirmation`, `import_job.ocr_paused`,
  `import_job.committed`, `import_job.failed`, and `import_job.attempt_finished`.
- Narration: `tts_job.scheduled`, `tts_job.started`, `tts_job.state_changed`,
  per-chapter start/heartbeat/cache/skip/completion events, `tts_job.failed`, and
  `tts_job.attempt_finished`.
- AGY: worker lock/preflight/heartbeat events; `agy.job_claimed`,
  `agy.run.started`, `agy.run.completed`/`failed`/`canceled`, run-state changes,
  subprocess start/spawn/exit, provider waits, orphan recovery, and the final job attempt.
- Other background work: the translation prefetch task emits
  `background_task.started`, `background_task.completed`, or `background_task.failed`.
- Provider calls: `ai.provider_call_started`/`completed`/`failed` records provider,
  operation, model, attempt/retry timing, size/count metadata, HTTP status, and token
  usage when returned. Gemini also reports durable budget charges and rate-limit waits.
- Process/request health: `worker.started`/`stopped`/`loop_failed`, application lifecycle
  hook events, and `http.request.completed`/`failed`.

Messages are human-readable, but dashboards and alerts should filter on `event`, `level`,
and structured fields rather than matching message text.

## Loki / Grafana query examples

Replace the selector labels below with those assigned by the installed Docker or journald
collector. Parse JSON at query time and keep high-cardinality values such as `job_id`,
`worker_id`, `request_id`, and `ai_run_id` as fields—not permanent Loki stream labels.

```logql
# Everything for one durable job, across schedule, retries, and completion
{container_name="novelwiki-web"} | json | job_id="42"

# Failed or crashing background work
{container_name=~"novelwiki-web|novelwiki-agy-worker"}
  | json | level=~"error|critical" | job_system!=""

# AGY translation runs and their subprocess exits
{unit="novelwiki-agy-worker.service"}
  | json | agy_workload="translate_batch"

# Lease/heartbeat trouble that can explain unexpected requeues
{container_name="novelwiki-web"}
  | json | event=~"worker.lease_heartbeat_failed|job.lease_recovered"

# One user action on the synchronous request side
{container_name="novelwiki-web"} | json | request_id="req-123"
```

A useful first dashboard has queue counts from PostgreSQL beside log panels for failed
attempts, retries/lease recoveries, p95 `duration_ms` by `job_kind`, AGY preflight/provider
waits, import OCR pauses, and TTS chapter generation time. Alert on worker loop/process
failures, AGY preflight failures, repeated lease-heartbeat failures, and terminal job
failures; do not alert on ordinary idle polling (it intentionally emits nothing).

## Sensitive-data boundary

Structured lifecycle fields never intentionally include prompts, chapter/story text,
generated translations/codex output, AGY stdout/stderr content, authentication material,
cookies, or provider keys. Common bearer tokens, secret assignments, and URL passwords are
redacted as defense in depth. Avoid adding raw `options`, request bodies, query strings, or
provider payloads to future events.

AGY stdout/stderr byte counts and truncation flags are logged, but content remains only in
the private mode-0700 workspace. Per-run `logs/runner.jsonl` and `logs/agy.log` remain
available under `AGY_WORK_DIR` for a privileged incident investigation and follow the
configured success/failure retention windows.

## Direct operator access

```bash
# Web JSON logs under Compose
docker compose logs -f web

# Dedicated user-level AGY worker JSON logs
journalctl --user -u novelwiki-agy-worker.service -f -o cat

# Validate that a line is JSON
docker compose logs --no-log-prefix web | tail -n 1 | python -m json.tool
```

If the stream is empty, confirm the process was restarted after changing logging settings
and verify the collector reads container stdout or the user journal. If job events stop but
HTTP events continue, check `worker.started`, application startup-hook events, and
`worker.loop_failed` before manually retrying work.
