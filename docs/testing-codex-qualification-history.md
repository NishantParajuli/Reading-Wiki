# Historical Codex provider qualification

This record preserves the dated provider canaries and subsequent contract qualification
notes previously embedded in `testing.md`. Test counts, rollout status, provider names,
and operational outcomes below describe their recorded revisions, not the current
checkout. Use [testing.md](testing.md) for current commands and
[release-runbook.md](release-runbook.md) for release requirements.

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
