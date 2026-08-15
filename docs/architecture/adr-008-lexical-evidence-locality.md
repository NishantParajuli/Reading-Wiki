# ADR-008: Match evidence anchors as exact lexical sequences

- Status: accepted
- Date: 2026-08-03

## Context

Artifact schema 2.2 introduced verbatim evidence anchors and a semantic verifier. Its first
normalizer still compared punctuation inside an anchor. A chapter-24 verifier retained the exact
source words but omitted some dialogue delimiters while copying several multi-line quotations. The
host classified four supported items as non-verbatim, exceeded the absolute quarantine threshold,
and retried the chapter. One other item really had changed `her` to `my` and needed quarantine.

Adding individual exceptions for straight quotes, curly quotes, dashes, ellipses, or Markdown line
wrapping would leave the same failure mode open for the next presentation character.

## Decision

OpenAI Codex contract 1.3.4 and AGY plugin 1.4.4 keep artifact schema 2.2 but define literal anchor
locality as an exact, boundary-aware source-word sequence inside one cited chunk. The host and
isolated plugin hook apply the same normalization:

- normalize Unicode, case, and apostrophe typography;
- tokenize letters and numbers while preserving internal apostrophes;
- ignore punctuation, dialogue delimiters, and whitespace; and
- retain exact token boundaries, words, and word order.

This is a locality check, not a semantic similarity check. A changed pronoun, name, number, value,
or word order remains invalid. The independent verifier still decides whether the source passage
entails the reader-facing claim. Residual invalid items remain subject to item-level quarantine and
the broad-failure threshold from ADR-007.

## Consequences

- Presentation differences cannot consume a whole-job attempt.
- Paraphrased claims remain valid when they carry an exact source-word anchor.
- The validator still rejects the genuine `her`/`my` change from the triggering artifact.
- The triggering verifier artifact retains 52 grounded material items and quarantines only that
  single changed-word event under the new contract.
- Persisted pipeline and database schemas are unchanged, so committed chapters need no rebuild.
