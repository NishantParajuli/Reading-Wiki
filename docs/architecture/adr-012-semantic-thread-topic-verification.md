# ADR-012: Verify bounded semantic plot-thread topic matches

- Status: accepted
- Date: 2026-08-05

## Context

Chapter 135 explicitly advances Sylphiette's reconnection with Rudeus: Fitz decides that she must
reveal who she is and how she feels to Rudy. The trusted plot-thread vocabulary used Sylphiette and
Rudeus, while the chapter used the Fitz persona and Rudy nickname. The lexical host check rejected
the valid update before the configured independent verifier could judge its meaning.

Removing topic validation would allow any scene sharing a participant to drift an unrelated plot
thread. Dropping every lexical miss would avoid failure but lose valid durable developments.

## Decision

OpenAI Codex contract 1.3.8 keeps artifact schema 2.2 and deterministic stable-title/keyword
matching as the default. With separate verification enabled, the primary host records lexical
topic misses as exact group/index/ref issues and supplies the trusted title, keywords, and
participants to the verifier. The verifier is explicitly instructed to retain an update only when
current-chapter evidence semantically advances that thread; participant sharing alone is not proof.

The final host permits at most one verifier-retained lexical miss and requires the update to carry
at least two trusted participants, or the sole trusted participant for a one-participant thread.
Multiple misses or weaker continuity fail with `thread_relevance_broad_failure`. Dormant-thread
updates remain outside this recovery path and always require `reopen`.

The transaction workflow carries an explicit `thread_relevance_verified` flag only from a validated
`codex_verify` artifact. The transaction-bound writer repeats the same bounded semantic check
against the locked chapter text and sealed context manifest. Other callers retain strict lexical
validation.

## Consequences

- Alias, persona, nickname, and paraphrase wording can preserve a valid thread development.
- The exact chapter-135 Fitz/Rudy update can reach semantic verification.
- An unrelated scene sharing only one thread participant cannot use the override.
- Broad topic drift still retries rather than silently entering the Codex.
- Persisted schemas and existing pipeline-2.1 commits are unchanged.
