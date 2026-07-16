# ADR 004: Codex extraction uses bounded, hierarchical, temporal memory

Status: Accepted — 2026-07-15

## Decision

Codex extraction must not scale its prompt with the novel's total entity/fact count.
Each chapter uses one deterministic, spoiler-safe context capped by tokens and entity
count: current chunks; three recent grounded chapter summaries; completed checkpoint/
volume memory; folded current state; relevant open plot threads; and ranked entities.
The direct API and AGY transports share this builder and strict v2 proposal contract.

Historical facts remain append-only, while mutable truth is an ordered state-transition
log with certainty, perspective, narrative scope, provenance, and supersession. Chapter
summaries are current-chapter-only. Completed twenty-five-narrative-chapter checkpoints are
recomputed from those child summaries; no partial checkpoint row is generated or fed forward.
Volume summaries are optional: they are emitted only at the final narrative chapter of a
non-empty database `part_label`, never from an AI-inferred boundary, and retain immutable
range/through/source/checkpoint hashes.

Every commit takes a per-novel advisory lock and revalidates both the row-locked chapter
source hash and a freshly rebuilt context hash. Only supplied/declared local refs may be
committed. Builds are deduplicated per novel and pipeline version; overlapping range jobs
are not allowed.

## Consequences and trade-offs

- Chapter 1,400 has bounded prompt cost/attention instead of inheriting the whole book.
- Selection can omit a relevant entity. Exact names/aliases have dominant rank, while
  activity, open threads, graph, trigram, and vector signals reduce misses; omitted names
  can still be declared provisionally and deterministically linked against the full DB.
- Hierarchical compression loses detail, so raw chunks and historical structured facts
  remain the retrieval source of truth. Summaries guide extraction; they do not replace
  citations.
- State quality depends on the extractor correctly distinguishing current reality from
  belief, history, dreams, and prophecy. The transition log preserves those qualifiers so
  later repair/recomputation remains possible.
- Context hashes make resume/commit safer but deliberately reject work if an earlier
  chapter commits while the model is running. The job retries with the new context.
- Books without reliable volume labels receive universal checkpoints but no volume rows.
  This is intentional; false boundaries are worse than a missing optional layer.
- v1 rows remain readable during rollout, but a v2 build does not treat a v1 extraction
  checkpoint as complete. Rebuilding migrates selected chapters in place; `reset-codex`
  is available when operators prefer a clean full regeneration while retaining embeddings.
