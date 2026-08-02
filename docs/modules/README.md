# Module reference

One deep-dive document per business module. Every module follows the standard internal
layout documented in [../architecture/module-anatomy.md](../architecture/module-anatomy.md);
these pages cover what is *specific* to each: its responsibility, owned tables, public
contract, notable internals, HTTP/CLI/worker surfaces, and how it collaborates with the
rest of the system.

| Module | Doc | One-liner |
|---|---|---|
| Identity | [identity.md](identity.md) | accounts, sessions, OAuth, email flows, rate limits, quotas, admin user management |
| Catalog | [catalog.md](catalog.md) | the novel aggregate: metadata, ownership/visibility, per-user libraries, tag suggestions |
| Reading | [reading.md](reading.md) | chapters, progress, bookmarks, overlays, contributions, the trusted spoiler ceiling |
| Acquisition | [acquisition.md](acquisition.md) | scraping + EPUB/PDF import jobs + extracted assets |
| Translation | [translation.md](translation.md) | on-demand/batch translation and the per-novel glossary |
| Codex | [codex.md](codex.md) | the spoiler-safe knowledge base: build pipeline, retrieval, Ask, recap |
| Narration | [narration.md](narration.md) | audiobook TTS jobs and the chapter-audio cache |
| Work | [work.md](work.md) | the generic durable-job system: schedule, dedupe, lease, retry, settle quota |
| AI Execution | [ai-execution.md](ai-execution.md) | API/AGY/OpenAI Codex policy, provider gateways, cost controls, isolated runners |
| Experience | [experience.md](experience.md) | read-only cross-module projections: home, activity, discover, profiles, admin |

## Dependency shape (executable graph)

Arrows mean "consumes an injected capability of" (all injections happen in Bootstrap;
types flow through `public.py` only):

```
                 ┌────────────┐
                 │  identity  │◀── everyone (principals, quota, sessions)
                 └────────────┘
   ┌───────────┐   ┌───────────┐   ┌───────────┐
   │  catalog  │◀──│  reading  │◀──│   codex   │  (reading text → codex artifacts)
   └───────────┘   └───────────┘   └───────────┘
        ▲              ▲   ▲             ▲
        │              │   └─────────────┼──────────┐
   ┌────┴──────┐  ┌────┴─────┐   ┌───────┴───┐  ┌───┴─────────┐
   │acquisition│  │translation│  │ narration │  │ai_execution │◀─ codex/translation/
   └───────────┘  └──────────┘   └───────────┘  └─────────────┘   acquisition (backends)
        ▲              ▲               ▲
        └──────────────┴───────┬───────┘
                          ┌────┴───┐        ┌────────────┐
                          │  work  │        │ experience │── read-only projections
                          └────────┘        └────────────┘   over everyone's tables
```

The graph is acyclic (checker-verified). Experience is special: it never writes and never
exposes capabilities to others; it *reads* across owners through registered projections.

## Table ownership

The authoritative single-writer table is
[../architecture/module-ownership.md](../architecture/module-ownership.md); the full
column-level schema is [../data/database-schema.md](../data/database-schema.md).
