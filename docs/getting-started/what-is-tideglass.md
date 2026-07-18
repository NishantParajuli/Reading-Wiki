# What is Tideglass?

Tideglass (code package: `novelwiki`) is a self-hosted, **multi-user reading platform**
for webnovels and ebooks. One server instance serves many readers, each with their own
account, library, progress, and monthly spending quotas.

## The elevator pitch

Bring a story in from anywhere — **scrape** it chapter-by-chapter from a website, or
**import** an EPUB/PDF (digital *or* scanned — scans get OCR'd) — and read it in a cozy,
distraction-free reader. If the story is in another language, chapters are **translated
on demand** as you open them, with names kept consistent by a per-novel glossary. Any
chapter can be **narrated** as an audiobook in a consistent cloned voice. And any novel
can opt into a **codex**: an AI-built encyclopedia of characters, facts, relationships,
and events that is *spoiler-safe* — it only ever shows you information from chapters you
have actually read.

## The one invariant

The codex upholds a single hard rule, and half the architecture exists to serve it:

> When you are reading at chapter N, no information from any chapter > N may ever appear
> in a codex entry, a stat, a Q&A answer, or a recap.

This is enforced in the database and retrieval layers (every read filters
`chapter <= your ceiling`), never by asking an AI model to hold back. Your ceiling comes
from what the *server* has watched you read — the browser can't lie its way past it.
Full explanation: [../concepts/spoiler-safety.md](../concepts/spoiler-safety.md).

## Feature tour (mapped to the modules that own them)

| You see | What it does | Owned by |
|---|---|---|
| **Home** | continue reading / continue listening, your running jobs, recent imports, newest shared novels | Experience |
| **Library / Discover** | your shelves (`to_read`/`reading`/`completed`); browse the shared (public/global) library with filters and provenance badges; "add to library" shares one text among many readers | Catalog + Experience |
| **Accounts** | email+password (Argon2), optional Google/Discord sign-in, email verification, password reset, public profiles `/u/<name>`, avatars, synced reader prefs | Identity |
| **Reader** | themes/width/auto-scroll, volume-grouped TOC, bookmarks, scroll recovery, translation editing, audiobook transport | Reading (+ Narration) |
| **Scraping** | multi-source stitching with per-site adapters, incremental, stops at paywalls | Acquisition |
| **Import** | EPUB/PDF upload (chunked for big files), OCR with cost confirmation, an editable segmentation plan you review before committing | Acquisition |
| **Translation** | on-demand + prefetch, per-novel glossary, personal overlays on shared novels + contribute-back to the owner | Translation + Reading |
| **Audiobooks** | per-chapter or whole-book narration jobs, cached Opus, streamed with scrubbing | Narration |
| **Codex** | Browse entities, profiles, timelines, identity-reveal banners, **Ask** (cited Q&A), no-spoiler **recap** — all bounded by your chapter ceiling | Codex |
| **Jobs** | one feed over every background job (scrape/import/codex/translate/narration) with progress and cancel | Work + Experience |
| **Quotas & costs** | monthly per-user caps on everything that costs money, cost estimates *before* you spend, refunds on failure | Identity + Work |
| **Admin** | user management, platform spend, moderation, AI-backend grants | Experience (+ owners) |

## The cast of external services

- **PostgreSQL** (with `pgvector` + `pg_trgm`) — the one database.
- **DeepSeek** (optional) — native V4 Flash/Pro generation for translation, extraction,
  segmentation, and Q&A when `DEEPSEEK_API_KEY` is set.
- **OpenRouter** — embeddings and reranking always; also the generation fallback when
  native DeepSeek is not configured or a non-DeepSeek model id is selected ("Flash
  reads, Pro thinks" two-model split by default).
- **Gemini** (optional) — vision OCR escalation for scanned PDFs, held inside its free
  tier by persistent budget counters.
- **GPU sidecars** (optional) — PaddleOCR (`:8077`) and OmniVoice TTS (`:8078`), each a
  separate Docker service so the web image stays GPU-free.
- **AGY / Antigravity CLI** (optional, admin-granted) — an alternative execution backend
  that drives a subscription account instead of the metered API
  ([../pipelines/ai-backends.md](../pipelines/ai-backends.md)).

## Where the name things live

- Product name: **Tideglass** (cookies `tg_*`, frontend package `tideglass-frontend`).
- Historical name: **NovelWiki** — the Python package `novelwiki/`, container names, DB
  name. Both refer to the same thing; docs use Tideglass for the product and `novelwiki`
  for code paths.

## Next steps

- Run it: [local-setup.md](local-setup.md)
- Find your way around the repo: [repo-tour.md](repo-tour.md)
- Understand the architecture: [../architecture/overview.md](../architecture/overview.md)
- New to the underlying concepts? [../concepts/primer.md](../concepts/primer.md)
