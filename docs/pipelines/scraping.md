# Pipeline: scraping

> How chapters get from a webnovel site into `chapters`, safely and resumably.
> Module reference: [../modules/acquisition.md](../modules/acquisition.md).

## Concepts

- **Source** — a `(novel, site)` pair with an `adapter` key, a `start_url`, `language`,
  `is_raw`, and a **`chapter_offset`**. A novel may have several sources (an English
  site to ch. 124 + a raw site from 125): `global_number = source_local_number +
  chapter_offset` maps them all onto one continuous reading sequence.
- **Adapter** — per-site scraping technique in
  `modules/acquisition/adapters/outbound/scraper/adapters.py`. Built-ins: `fenrirealm`,
  `readhive`, `boti-translations`, `69shuba`, `wetriedtls`. Each knows how to fetch a
  chapter page, extract title/content, find the next-chapter link, and recognize a
  premium wall. New site = subclass `BaseAdapter` (or `_PagedHtmlAdapter`) + register in
  `ADAPTERS`; it then appears in the UI dropdown via `list_adapters()` and
  `GET /api/adapters`.

## Flow

1. **Trigger** — `POST /api/novels/{id}/scrape` (owner/admin; optional `source_id`,
   `max_chapters`) schedules a durable Work job (`kind='scrape'`,
   idempotency-deduped — a second click attaches to the running job); or CLI
   `scrape <novel_id> --max 50` runs it directly. Scraping consumes no quota.
2. **Resume point** — the runner (`scraper/runner.py`) asks Reading for the source's
   `resume_url` (the last scraped chapter's next link, or `start_url` on first run).
3. **Loop** per chapter: safe-fetch the page → adapter parses `(title, content_html,
   next_url)` → text cleanup → **`upsert_ingested_chapter`** through Reading's ingestion
   capability (computes the global number from the offset; sets `original_text` vs
   `content` by `is_raw`; respects `force`; never regresses `content_version`) →
   progress update + cancel check → politeness delay (`SCRAPER_DELAY`).
4. **Stop conditions** — no next link, `--max` reached, cancel requested, or a
   **premium wall** detected (stops cleanly; job is `done` with a stage note, so
   re-scraping after buying/waiting continues where it left off). `touch_novel` bumps
   freshness for Discover.

## Safety: `safe_fetch.py` (the SSRF boundary)

All scraper traffic goes through one hardened fetch:

- **HTTP(S) only**; URL scheme/userinfo validation.
- **Public-address pinning** — DNS results must resolve to public IPs (no RFC1918,
  loopback, link-local, metadata ranges); redirects are re-resolved and re-checked
  hop by hop.
- **Same-host binding** — with `SCRAPER_REQUIRE_SAME_HOST=true` (default), the crawl
  (including redirects and CDN/API hops) must stay on the source's host. Adapters
  declare known secondary hosts explicitly (`allowed_hosts = ["api.example.com"]`);
  `SCRAPER_ALLOWED_HOST_OVERRIDES` exists for deployment-level exceptions — prefer the
  adapter-local list.
- **Response caps** — `SCRAPER_MAX_RESPONSE_MB` (8) and `SCRAPER_TIMEOUT_SECONDS` (30).
- **TLS-fingerprint-resistant client** — `curl-cffi` impersonation, because several
  target sites block vanilla HTTP clients.

Adversarial coverage: `novelwiki/eval/scraper_security_tests.py`.

## Multi-source stitching & renumbering

Adding a continuation source is: `POST /api/novels/{id}/sources` with the right
`chapter_offset` (e.g. 124 if the raw site's "chapter 1" is global 125). If the offset
was wrong, `PATCH /api/novels/{id}/sources/{sid}` renumbers every chapter of that source
atomically via the `update_source_offset` workflow — refused while codex artifacts exist
on the old numbering (clear/rebuild the codex first). Overlaps with chapters from other
sources are detected via `other_source_numbers` so two sources don't fight over one
global number.

## Interactions

- Raw sources (`is_raw`) feed [translation.md](translation.md) — `original_text` is
  stored, `translation_status='none'` until read/translated.
- New chapters make the codex *stale*, visible in the novel health panel; the next
  build extends it ([codex-build-and-ask.md](codex-build-and-ask.md)).
- Imported books register an import source and flow through the exact same
  `upsert_ingested_chapter` funnel ([file-import.md](file-import.md)).
