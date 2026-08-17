# Testing NovelWiki

Backend integration tests create a random `tg_pytest_*` database and destroy it after
the run. They never use the configured application database directly. The launcher
deliberately refuses to infer destructive-test authority from the app's `DATABASE_URL`:
point both variables at a PostgreSQL/pgvector server on which the test user may create
and drop databases. The named app database is only a naming/connection template.

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:5432/novelwiki \
TEST_DB_SUPERUSER_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres \
  uv run python scripts/test_backend.py
```

The launcher maps Docker's `host.docker.internal` to `127.0.0.1` when tests run on
the host. Connections fail within five seconds and diagnostics contain only the host and
database name, never credentials.

Architecture-only tests do not require PostgreSQL:

```bash
uv run pytest -q tests
```

AGY contract/runner/workload suites use `novelwiki/eval/fake_agy.py` and do not consume
subscription capacity. The authenticated CLI canary is opt-in because it makes real model
requests:

```bash
export TEST_DATABASE_URL=postgresql://test-user:password@127.0.0.1:5432/novelwiki_test
export TEST_DB_SUPERUSER_URL=postgresql://test-admin:password@127.0.0.1:5432/postgres
RUN_REAL_AGY_TESTS=1 uv run pytest -q novelwiki/eval/agy_real_cli_tests.py -m agy_real
```

For the pinned AGY 1.1.2 binary, the canary requires a completed `READY` artifact, a manifest
finalized by the trusted stop hook, both loaded safety hooks, and bounded model requests. The
runner tests separately prove that planner/tool steps with output progress are allowed while a
no-progress loop is killed. A non-committing real-data Codex canary is available with repeated
chapter flags sharing one preflight:

```bash
uv run python scripts/diagnose_agy_codex.py --novel-id 33 \
  --chapter 1 --chapter 2 --chapter 3 --chapter 4 --chapter 5
```

Keep the default-off Codex kill switch until representative chapters pass on the exact pinned
binary/plugin pair and the operator intentionally enables rollout.

OpenAI Codex App Server tests use a fake JSONL subprocess and host-side artifact
materialization, so the normal suite consumes no ChatGPT capacity. The authenticated
preflight is also non-consuming: it verifies the pinned CLI, initializes App Server,
checks `account/read`, and lists configured models without starting a turn:

```bash
uv run python -m novelwiki.modules.ai_execution.adapters.outbound.openai_codex.preflight
```

The admin OpenAI Codex smoke action is intentionally separate because it starts a real,
rate-limited model turn. Run it once during rollout, then qualify representative translation
and extraction chapters before enabling either global switch for general use; see the
[OpenAI Codex operator runbook](openai-codex-operator-runbook.md).

`agy_workload_tests.py::test_chapter_1200_context_stays_bounded_and_ignores_historical_fact_bloat`
is the provider-free long-book qualification. It creates a synthetic LOTM-shaped chapter/volume
layout, 500 entities, temporal state, threads, and more than 20,000 historical facts in the
disposable database; then it proves chapter 1,200 context is deterministic, ceiling-safe, and
within every configured entity/section/total budget. Run with `-s` to print the measured context
tokens, selected/dropped entity counts, and packing time.

### Dated Codex v2 provider qualification (2026-07-16)

These paid canaries used real Lord of the Mysteries chapter 1 in disposable databases; production
was read-only and the disposable databases were removed afterward.

- Direct API (`deepseek/deepseek-v4-flash`) completed extraction, verification, and the
  grounded chapter summary in exactly three chat calls. The committed proposal had valid
  source/context hashes and provenance; rerunning the completed chapter made no provider call.
- One real `perplexity/pplx-embed-v1-0.6b` smoke call returned a normalized 1,024-dimensional
  vector.
- AGY plugin `1.3.1` (`Gemini 3.5 Flash (High)`) completed a real chapter-1 v2 run under an
  eight-request ceiling: trusted artifact validation passed, the proposal committed atomically,
  and the run persisted `completed`. A disposable diagnostic wrapper then failed while formatting
  a nonexistent reporting-only preflight field; this occurred after application completion and was
  not rerun to avoid unnecessary paid usage.

This evidence qualifies the early chapter path, shared commit contract, and bounded context. It
does **not** claim that late, checkpoint-end, or final-volume AGY canaries have passed; those remain
explicit production rollout gates in the
[AGY operator runbook](agy-operator-runbook.md#codex-v21-quality-rollout).

### Dated Codex v2.1 OpenAI qualification (2026-08-03)

The production candidate was backed up and reset at the structured-Codex boundary before this
qualification. Source chapters, chunks, and embeddings were preserved. A real OpenAI Codex App
Server smoke turn completed on `gpt-5.6-luna`, followed by an earliest-narrative-chapter extraction
and an independent verification turn on the same model at `max` reasoning effort. Contract `1.2.0`
and pipeline `2.1` completed on the first candidate attempt with zero stderr. The committed chapter
used all eight current-chapter chunks, selected no irrelevant background entities, and stored a
124-token summary, nine facts, four events, and one state transition without relationship or thread
noise. Two prior non-committing calibration drafts independently converged on the same named entity
and comparable claims; their 78- and 87-token summaries established the 64-token validation floor
while the model prompt continues to target 80-220 tokens and the hard cap remains 300.

The same revision passed 415 architecture/unit/contract tests, 245 disposable-database evaluations
with two opt-in tests skipped, 36 frontend unit tests, 12 mocked critical-path browser tests with one
real-backend scenario skipped, the production frontend build, and the nine-path real browser/backend
test against a disposable database. This qualifies the earliest-chapter OpenAI path and separate
verification contract. It does **not** yet qualify the chapter-25 checkpoint, repaired epilogues,
later-volume context, or the full chapter-250 corpus; those require auditing the chronological
production rebuild as it reaches each gate.

The subsequent contract `1.3.0` chapter-4 qualification deliberately kept every failed calibration
artifact non-committing. Those artifacts exposed and regression-tested compound and negation
locality, same-chapter proposed-alias subject terms, same-chapter persona duplication, redundant
canonical aliases, and verifier-only worker-loss recovery. After those host fixes, a fresh
Luna/max extraction and independent Luna/max verifier completed on their first attempt with zero
stderr and atomically committed the verifier artifact. The result stores `Rudy` as one reveal-timed
alias on the existing protagonist, adds only the named `Japan`, `Earth`, and `Healing` entities,
and contains a 128-token summary, six facts, one relationship, one event, six state transitions,
and one durable plot-thread update with zero redundant canonical aliases. The current revision
passes 420 architecture/unit/contract tests and the same 245 disposable-database evaluations with
two opt-in skips. This qualifies the next chronological chapter and the anti-bloat alias path; the
checkpoint, epilogue, later-volume, and chapter-250 gates remain pending on the durable continuation.

Contract `1.3.1` then exercised the first long-range continuation at chapter 5. Two pre-fix drafts
failed closed without a commit because the locality tokenizer treated `Rudeus's` as distinct from
`Rudeus`, even though the cited passage contained the named family members. The possessive-token
regression now covers straight and curly apostrophes. After the fix, a fresh Luna/max extraction
and independent Luna/max verifier both passed on the first attempt and atomically committed chapter
5. The result contains a 129-token summary spanning all eight evidence chunks, nine named entities,
one reveal-timed alias on the existing protagonist, 26 facts, 13 relationships, five events, eight
entity-state transitions, three relationship-state transitions, and one existing-thread advance.
Manual review found the detail proportional to the chapter's multi-year Lilia backstory and family
setup rather than generic or duplicate-name inflation. The durable 5–250 job advanced to chapter 6;
later checkpoint, epilogue, volume, and final-corpus gates remain unqualified until it reaches them.
The current revision passes 422 host-side tests and 245 disposable-database evaluations with two
opt-in skips.

Contract `1.3.2` supersedes only the OpenAI reasoning-effort choice: Luna now uses `xhigh` for
extraction and the still-mandatory independent verifier. The in-flight max job was canceled at the
chapter boundary with chapter 5 preserved, then the durable continuation resumed at chapter 6.
The first xhigh chapter passed both model turns and every unchanged host validator on its first
attempt, committing in 8 minutes 43 seconds versus roughly 15 minutes for the preceding max-effort
chapter (about 42% lower wall time in this initial, chapter-dependent comparison). It stored a
134-token summary spanning all 13 evidence chunks, nine named entities, one alias, 22 facts, two
relationships, three events, 11 entity-state transitions, two relationship-state transitions, and
one existing-thread advance. Manual inspection found the entities limited to named books,
characters, and spells and the summary appropriately focused on language, reading, and magic
training. One chapter is a canary rather than a corpus-wide performance or quality guarantee.

Contract `1.3.3` replaces artifact schema 2.1's shared-word citation-locality heuristic with
artifact-schema 2.2 evidence anchors. Provider-free regressions cover the chapter-15 class of valid
paraphrase (`thank you for having me` supporting a giving-birth claim), wrong-chunk anchors,
case/whitespace/quotation normalization, shared-vocabulary-but-nonentailing claims remaining the
semantic verifier's responsibility, isolated item quarantine, broad-failure retry thresholds,
dependent identity-state quarantine, targeted verifier task instructions, strict Structured
Outputs exposure, AGY stop-hook enforcement, and retry progress based on durable chapter position.
Run the focused gates with:

```bash
uv run pytest -q \
  tests/unit/codex/test_quality_contracts.py \
  tests/unit/ai_execution/test_openai_codex_app_server.py \
  tests/unit/ai_execution/test_agy_codex_dispatch.py
HOST_WORKER_DATABASE_HOST=127.0.0.1 uv run pytest -q \
  novelwiki/eval/agy_workload_tests.py \
  novelwiki/eval/agy_contract_tests.py
```

These deterministic gates do not replace a real Luna/xhigh schema-2.2 canary. Before resuming a
long production build, verify one normal chapter plus one deliberately paraphrased fixture and
inspect the verifier/quarantine logs without exposing story text.
The 2026-08-03 contract-1.3.3 candidate passed 437 host-side tests and all 245
disposable-database evaluations, with the two documented opt-in skips.
An isolated, database-free Luna/xhigh `codex_verify` canary then exercised the exact false-positive
pattern: it retained the giving-birth paraphrase with the literal `thank you for having me` anchor,
returned schema 2.2 with zero host anchor issues, and consumed 15,931 total provider-reported
tokens. This proves the new contract path accepts that representative paraphrase; it is not a
corpus-wide accuracy measurement.

Contract `1.3.4` / plugin `1.4.4` retains schema 2.2 and changes only anchor locality's
representation rule: both validators compare boundary-aware exact source-word sequences, ignoring
punctuation, quote delimiters, apostrophe typography, and whitespace. Regressions retain all words
from the chapter-24 dialogue fixture while varying presentation, then prove that a changed value or
pronoun still fails. The exact failed chapter-24 verifier artifact leaves one genuine changed-word
issue for quarantine instead of four punctuation false positives.

Contract `1.3.5` retained the exact chapter-39 verifier artifact's supported `Stone Treants`
concept fact and committed that chapter in production after 451 host-side tests passed. Contract
`1.3.6` extends the same no-fuzzy alignment rule to regular possessive number: both failed
chapter-41 verifier artifacts now align all `Adventurers' Guild` claims to the trusted
`Adventurer's Guild` organization term, while a dropped possessive marker remains invalid.

Contract `1.3.7` covers the duplicate-thread failures observed in chapters 49 and 70. Provider-free
regressions prove that strict single-pass validation still rejects duplicate refs, the two-pass
path can defer an existing-thread duplicate and a new `p1` open-plus-advance pair to verification,
and one residual duplicate retains the first grounded update. Two or more residual duplicates raise
`thread_update_broad_failure` so broad thread loss cannot be hidden. The verifier task also names
the exact duplicate group, indexes, ref, and first occurrence.

Contract `1.3.8` replays the exact chapter-135 failure where the trusted thread is “Sylphiette's
reconnection with Rudeus” but the source uses the Fitz persona and Rudy nickname. The first pass
records an exact semantic topic-review issue instead of aborting before verification. Regressions
prove that one verifier-retained update with both trusted participants is accepted, an unrelated
Fitz/Rudy scene represented with only one trusted participant fails, multiple retained lexical
misses raise `thread_relevance_broad_failure`, dormant updates still require `reopen`, and the
atomic commit gate preserves the verified policy instead of reverting to lexical-only rejection.

Contract `1.3.9` replays both chapter-149 verifier artifacts. The first contained five semantically
valid anchors that skipped six or fourteen intervening source tokens; the second contained three
such anchors plus one exact passage cited to the adjacent overlapping chunk. The verified-only
canonicalizer restores all nine to contiguous cited source spans with zero residual anchor issues.
Provider-free adversarial cases prove that changed numbers, reordered names, and distant stitching
remain invalid, while unverified extraction cannot request the repair policy.

Contract `1.3.10` replays both chapter-257 primary artifacts. Their full verifier tasks were 48,829
and 51,076 tokens, so the shared 48k cap rejected them before Luna verification and made the retry
deterministically useless. Compact draft JSON lowers the unchanged tasks to 47,156 and 48,751
tokens; the separate 64k verifier cap leaves 16,844 and 15,249 tokens of headroom while primary
extraction remains capped at 48k. Regressions prove the complete source and draft remain present,
the default primary cap still rejects the enlarged second-pass task, the verifier cap accepts it,
and configuration cannot set the verifier below primary or above 128k.

### Read-side grounding regression gates

`tests/unit/codex/test_read_side_grounding.py` is provider-free and exercises the interactive
quality boundary: hybrid retrieval automatically invokes reranking but retains fused candidates
when that provider is unavailable; question/profile citations must belong to supplied evidence;
Ask verifier failure cannot publish or cache an unchecked draft; deterministic findings force a
repair; and profile/model/grounding cache namespaces invalidate older generated prose. The broader
disposable-database spoiler and cost-control suites continue to cover trusted ceilings, cache-hit
ordering, concurrency cleanup, and tool clamps. These tests establish host behavior; representative
real-model questions across early, middle, late, negative-answer, identity-reveal, and obscure-detail
cases remain a release qualification rather than something inferred from unit tests.

The blocking local release-candidate checks are:

```bash
export TEST_DATABASE_URL=postgresql://test-user:password@127.0.0.1:5432/novelwiki_test
export TEST_DB_SUPERUSER_URL=postgresql://test-admin:password@127.0.0.1:5432/postgres

uv run python tools/check_architecture.py --strict
uv run pytest -q tests
uv run python scripts/contracts.py
uv run python scripts/test_backend.py
DATABASE_URL="$TEST_DATABASE_URL" DB_SUPERUSER_URL="$TEST_DB_SUPERUSER_URL" \
  uv run python -m novelwiki.db.schema
uv run python tools/benchmark_queries.py --database-url "$TEST_DATABASE_URL" --check
cd novelwiki/frontend
npm test
npm run build
npm run test:e2e
cd ../..
uv run python scripts/test_real_browser.py
```

The architecture checker enforces table writers/readers, an acyclic module graph, SQL-free inbound
adapters, removal of the frontend API facade, cross-module frontend import surfaces, and reviewed
screen-size limits. PostgreSQL integration tests cover locks, claims, quota races, offset renumbering,
import replacement, single- and batch-volume appends, concurrent automatic volume range allocation,
overlay conflicts, audio indexes, and spoiler ceilings. The PDF import suite also covers
cross-page paragraph rejoining, decorative-image
filtering, inferred and bare-filename volume metadata, and cover selection. Focused application
and frontend tests cover user metadata precedence, multi-file queueing, and manual series/volume
review controls. Narration timing unit tests cover sidecar duration capture, manifest validation,
sentence mapping within real paragraph boundaries, and the untimed legacy-audio fallback.
Playwright covers twelve critical browser scenarios with fetch-level fixtures, including mobile
narration highlighting and automatic reveal.

To rehearse a backup and restore using two hard-coded disposable databases:

```bash
TEST_DB_SUPERUSER_URL=postgresql://.../postgres scripts/rehearse-backup-restore.sh
```

The client image defaults to PostgreSQL 18. Set
`POSTGRES_CLIENT_IMAGE=postgres:<server-major>-alpine` when rehearsing against another supported
server major so dump and restore tooling match the target.

The script refuses non-`novelwiki_rehearsal_*` database names, verifies the restored table catalog
and every table's row count, and cleans up both databases even after a failure.
