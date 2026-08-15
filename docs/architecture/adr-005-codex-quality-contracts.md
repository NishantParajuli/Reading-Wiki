# ADR 005: Codex quality is enforced as a trusted data contract

Status: Accepted — 2026-08-03

## Context

The first 250-chapter audit found that structural completeness alone was misleading. Every
chapter could have chunks, embeddings, summaries, citations, entities, state, and memory while
still containing excluded epilogues, generic entities, semantically wrong ref attachment,
endpoint-only checkpoint summaries, stale current state, off-topic thread drift, or retrieval
candidates suppressed by fusion. Prompt wording did not make those properties enforceable.

## Decision

Codex pipeline 2.1 makes quality-sensitive properties host-validated and rebuild-scoped:

- Explicit epilogues/interludes/side stories are narrative inputs. A refinement model cannot
  demote their title signal to back matter.
- Literal current-chapter entities are selected before background context. Generic/unnamed
  mention surfaces are removed with dependent claims. User-facing claim text must explicitly
  name its referenced subject(s), contain no local refs, and overlap its cited passage.
- Chapter summaries have dynamic minimum and hard maximum sizes and may not expose extraction
  notation. Checkpoint/volume reducers copy every trusted child chapter, partition it exactly
  once across small key beats, and persist a host-rendered summary plus that coverage evidence.
- Transient state ages to unknown unless reconfirmed; confirmed death removes living-only
  projection fields. Existing plot threads require current-chapter title/keyword grounding,
  become projected dormant after a bounded age, and require explicit reopening.
- Hybrid retrieval reserves candidates from both sparse and dense sources before reranking.
  Sparse IDF is computed over the exact reader-ceiling corpus, not over future documents that
  are merely masked from the returned rows.
- The ChatGPT/Codex accuracy profile uses Luna at max effort for extraction, verification,
  disambiguation, and smoke workloads, with a separate verifier enabled. Terra is reserved for
  translation at xhigh. Configuration rejects weaker Luna/Terra effort overrides.

The contract and generated rows are versioned as 2.1. Existing pre-2.1 structured data does not
satisfy a 2.1 build; the quality rollout starts at the first narrative chapter.

## Consequences and trade-offs

- False structured claims are rejected even when a looser extractor could have committed them.
  A chapter may retry or fail closed until the backend produces an auditable proposal.
- Stronger summaries and a separate Luna/max verification turn increase build time and model
  capacity use. This is intentional for the accuracy-first long-book build profile.
- Expired transient state is represented as unknown, not guessed. Raw historical transitions
  remain available for audit and future recomputation.
- Exact ceiling BM25 indexes add bounded per-process memory and first-query build work; a small
  LRU prevents unbounded growth.
- A full structured rebuild is required to compare quality fairly because early entity names,
  refs, state, threads, and reducer children influence every later chapter.
