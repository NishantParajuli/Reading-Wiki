# Concepts primer (for newer developers)

> Every non-obvious concept this codebase uses, explained from first principles and tied
> to where it appears here. If you can follow this page, the rest of the docs will read
> smoothly. Skip freely — each section stands alone.

## Web basics

**HTTP & REST-ish APIs.** The browser talks to the server in request/response pairs:
a *method* (GET = read, POST = create/do, PUT/PATCH = update, DELETE), a *path*
(`/api/novels/42/progress`), headers, and often a JSON body. Status codes carry the
outcome: 2xx ok, 401 "who are you?", 403 "you may not", 404 "no such thing",
409 "conflicts with current state", 422 "your input is malformed", 429 "slow down",
5xx "we broke". Here: all 119 endpoints are listed in
[../api/http-api.md](../api/http-api.md); handlers live in each module's
`adapters/inbound/http.py`.

**Cookies & sessions.** HTTP is stateless, so after login the server hands the browser
a cookie it re-sends with every request. Tideglass stores a random *opaque token* in an
`httpOnly` cookie (JavaScript can't read it — theft-resistant) and keeps the truth in a
DB row (hash of the token → user). Deleting the row logs the session out everywhere.

**CSRF.** A malicious site can make your browser send requests to any server *with your
cookies attached*. Defense: require proof the request came from our own page — a header
that only our JavaScript would set, matching a cookie value (the "double-submit"
pattern). Implemented in `platform/web/factory.py`; explained in
[../operations/security.md](../operations/security.md).

**SSRF.** If a server fetches user-supplied URLs (our scraper does), an attacker can
point it at internal addresses (`http://169.254.169.254/…`, `localhost:5432`). Defense:
resolve DNS, verify the IP is public, re-check every redirect, bind to the expected
host. Implemented in `safe_fetch.py`
([../pipelines/scraping.md](../pipelines/scraping.md)).

**SPA (single-page app).** The frontend is one JavaScript bundle (React) that renders
every screen and calls the JSON API; the server serves that bundle as static files and
falls back to `index.html` for any non-file path so `/library` deep-links work.

## Python & async

**`async`/`await`.** One process handles thousands of concurrent requests by *yielding*
whenever it waits on I/O (DB, HTTP, disk). `await` marks the wait points; the event loop
runs someone else meanwhile. Rule of thumb here: any function touching DB/network is
`async`. CPU-heavy work that would hog the loop (BM25 tokenization) is pushed to a
thread (`asyncio.to_thread`, see `BM25_THREAD_OFFLOAD`).

**Type hints & `Protocol`.** `def f(x: int) -> str` documents and machine-checks types.
`typing.Protocol` defines an *interface by shape*: any class with matching methods
satisfies it, no inheritance needed. This codebase's entire boundary system — ports and
public capabilities — is Protocols. `@dataclass(frozen=True)` creates immutable value
objects (our DTOs).

**FastAPI + Pydantic + Uvicorn.** FastAPI maps functions to routes, validates
request/response bodies with Pydantic models (that's where 422s come from), and
generates OpenAPI docs (`/docs`). Uvicorn is the ASGI server process that runs it.
**Typer** is the CLI equivalent (functions → commands). **pydantic-settings** turns
environment variables into the typed `Settings` object.

## Databases

**PostgreSQL & SQL.** Tables with typed columns; rows; `SELECT/INSERT/UPDATE/DELETE`;
*indexes* to make lookups fast; *foreign keys* to keep references valid (with
`ON DELETE CASCADE` — delete children too — or `SET NULL`). We use **asyncpg** directly:
SQL strings live in each module's outbound repositories — there is deliberately **no
ORM**, so what runs is exactly what you read.

**Transactions & atomicity.** `BEGIN … COMMIT` makes several statements all-or-nothing.
When one *business operation* spans several modules' tables, we open one transaction and
pass each module a connection-bound capability — the **unit of work** pattern
([../architecture/workflows-and-transactions.md](../architecture/workflows-and-transactions.md)).

**Optimistic concurrency.** Instead of locking a row for the whole (slow) operation,
snapshot a version/hash first, do the work, then commit only if it still matches
(`content_version`, `expected_source_hash`). A mismatch means someone changed it —
refuse instead of overwrite.

**`FOR UPDATE SKIP LOCKED`.** The queue-claim trick: many generic/import workers run
`UPDATE … WHERE id = (SELECT … FOR UPDATE SKIP LOCKED)` and each claims a *different*
row without waiting — the heart of the generic Work and Import workers here. TTS uses a
single-instance queue with restart requeue plus advisory locks instead.

**Idempotency.** An operation you can safely repeat. Our schema DDL is idempotent
(`CREATE TABLE IF NOT EXISTS`), job scheduling is (an `idempotency_key` dedupes repeat
clicks), chapter upserts and audio generation are (already-done ⇒ no-op).

**pgvector & pg_trgm.** Postgres extensions: `vector` stores embeddings and does
similarity search (with an HNSW index for speed); `pg_trgm` matches strings by 3-letter
fragments, giving fuzzy name search ("Lin Xaun" still finds "Lin Xuan").

## Architecture patterns

**Modular monolith.** One deployable, but code partitioned into modules with enforced
ownership (each table has one writer). You get microservice-like boundaries without
distributed-system pain. [../architecture/overview.md](../architecture/overview.md).

**Vertical slices.** Organize by *feature*, not by *layer-kind*: everything about
translation sits together in `modules/translation/`, instead of one giant `models.py` /
`views.py` split by technology.

**Clean/Hexagonal ("ports & adapters").** Business logic at the center; it declares
interfaces (**ports**) for what it needs; the outside world plugs in **adapters**
(Postgres, HTTP, provider SDKs). Dependencies point *inward only* — the use case never
imports the web framework or the database driver. Payoff: you can unit-test business
rules with fakes and swap infrastructure without touching policy.
[../architecture/module-anatomy.md](../architecture/module-anatomy.md).

**Dependency injection & the composition root.** Instead of a function reaching out for
its dependencies (importing a global — a "service locator"), the dependencies are
*handed in* (constructor args, `runtime` bundles). The single place that knows every
concrete wiring is the composition root — `novelwiki/bootstrap/`
([../architecture/composition-root.md](../architecture/composition-root.md)).

**DTOs.** Small immutable data-carrier objects passed across boundaries instead of raw
dicts or ORM rows — the boundary's vocabulary stays explicit and stable.

**Contract/snapshot testing.** Freeze an external surface (routes, CLI help, schema) as
a committed artifact; any diff must be intentional and reviewed.
[../architecture/enforcement.md](../architecture/enforcement.md).

## Background work

**Why not just "run it after the response"?** In-process background tasks die with the
process — and we redeploy by replacing the process. So every long/costly task is a
**durable job**: a DB row a **worker** (an infinite poll loop) advances through a state
machine (`queued → running → done/failed/canceled`), surviving restarts.

**Leases & heartbeats.** A claimed generic/import job carries "who claimed it and when the claim was
last renewed". A worker renews (heartbeats) while alive; if the lease goes stale, the
worker is provably dead and the job is safely reclaimed. This is how N workers share one
queue without double-processing. It does not apply to the deliberately single-instance
TTS worker.
[../pipelines/background-jobs-and-quota.md](../pipelines/background-jobs-and-quota.md).

**Reserve/consume/refund.** Money-safety depends on the workload: codex and AGY
translation reserve up front and generic Work settles once; API translation and TTS
charge one completed unit at a time. The common goal is the same—never charge work that
did not land and never double-refund.

## AI / retrieval

**LLMs, tokens, prompts.** Large language models complete text; input+output are
measured in *tokens* (~¾ of a word) and billed per token — hence all the caps, budgets,
and quotas. A *prompt* is the instruction text; ours are versioned in each module's
`domain/prompts.py`. "**Flash reads, Pro thinks**": route cheap high-volume reading to a
small model and reserve the expensive model for planning/synthesis.

**Embeddings & vector search.** An embedding maps text to a list of numbers such that
similar meanings land near each other; "find related passages" becomes "find nearest
vectors" (cosine similarity, pgvector).

**BM25 (lexical search).** Classic keyword relevance scoring — exact words matter. It
catches what embeddings miss (names, rare terms) and vice versa.

**Hybrid retrieval + RRF + rerank.** Run both searches, merge with Reciprocal Rank
Fusion (score by *rank agreement*, no tuning), then let a **reranker** model re-order
the top candidates by true relevance and keep the best few.

**RAG (retrieval-augmented generation).** Don't ask the model from memory — retrieve
relevant passages first and make it answer *from them, with citations*. The codex's Ask
is agentic RAG: the model *plans* which retrieval tools to call, in a loop, with every
tool argument clamped and the spoiler ceiling injected server-side
([../pipelines/codex-build-and-ask.md](../pipelines/codex-build-and-ask.md)).

**OCR.** Turning page images into text (scanned PDFs): a local PaddleOCR model first,
with low-confidence pages escalated to a vision LLM.

**TTS & voice cloning.** Text → speech; a reference clip conditions the model so a whole
book keeps one narrator voice ([../pipelines/narration.md](../pipelines/narration.md)).

## Operations

**Docker & compose.** A container image is a frozen filesystem + command; compose runs
several containers on a private network. Our web image bakes in the code (deploy =
rebuild), sidecars are separate GPU services, and only the web port touches the host —
loopback-only, behind a Cloudflare tunnel
([../operations/deployment.md](../operations/deployment.md)).

**GPU sidecar.** Heavy ML models live in their own service so the main image stays
small and CPU-only; the app talks to them over private HTTP with a shared token.

**systemd (user) service.** The host's process manager; used for the dedicated AGY
worker (`deploy/novelwiki-agy-worker.service`) so it restarts on failure and starts at
boot.

**Audit log & request IDs.** Append-only "what happened" records (`audit_events`), each
tagged with the `X-Request-ID` of the HTTP request that caused it — so you can trace a
user click to every side effect it had.
