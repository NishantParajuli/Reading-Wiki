# Pipeline: scraping

> How chapters get from a webnovel site into `chapters`, safely and resumably.
> Module reference: [../modules/acquisition.md](../modules/acquisition.md).

## Concepts

- **Source** — a `(novel, site)` pair with an `adapter` key, a `start_url`, `language`,
  `is_raw`, and a **`chapter_offset`**. A novel may have several sources (an English
  site to ch. 124 + a raw site from 125): `global_number = source_local_number +
  chapter_offset` maps them all onto one continuous reading sequence.
- **Adapter** — per-site scraping technique under
  `modules/acquisition/adapters/outbound/scraper/`, registered by `adapters.py`.
  The [supported-sites reference](supported-sites.md) lists exact keys, accepted novel
  or chapter URLs, default languages, archive-password setup, and current limits.
  Each adapter owns navigation and yields normalized chapter text. New site = subclass
  `BaseAdapter` (or `_PagedHtmlAdapter`) + register in `ADAPTERS`; its metadata then
  appears in the UI via `list_adapters()` and `GET /api/adapters`.

## Flow

1. **Trigger** — `POST /api/novels/{id}/scrape` (owner/admin; optional `source_id`,
   `max_chapters`) schedules a durable Work job (`kind='scrape'`,
   idempotency-deduped — a second click attaches to the running job); or CLI
   `scrape <novel_id> --max 50` runs it directly. Scraping consumes no quota.
2. **Resume point** — the runner (`scraper/runner.py`) asks Reading for the source's
   `resume_url`: the URL of its highest-numbered stored chapter, or `start_url` on first
   run. It reopens that chapter to discover current next navigation. Archive checkpoints
   identify a prose section in the downloaded book. The adapter's limit includes one extra
   checkpoint on resume, so requesting one new chapter can still make progress. Force
   mode uses `start_url` again.
3. **Loop** per chapter: safe-fetch → adapter yields `ChapterData` (number, title, text,
   URL, optional raw HTML) → **`upsert_ingested_chapter`** through Reading's ingestion
   capability (computes the global number from the offset; sets `original_text` vs
   `content` by `is_raw`; respects `force`; never regresses `content_version`) →
   cancel checks → politeness delay (`SCRAPER_DELAY`) after each yielded chapter.
   Before saving, the runner requires nonblank content, finite numbers, and increasing
   source-local chapter order. It refuses an unnumbered resume because assigning new
   numbers could overwrite existing chapters.
4. **Stop conditions** — no next link, `--max` reached, cancel requested, or a
   **premium wall** detected (stops cleanly with the number of stored chapters). A later
   scrape can continue if the site makes more chapters publicly available. Scraping does
   not inherit a reader's browser login. Fetch failures, missing expected content, and
   broken navigation fail the job rather than being reported as a premium boundary.
   A completed run updates the source's `last_scraped_at` timestamp.

## Safety: `safe_fetch.py` (the SSRF boundary)

All scraper traffic goes through one hardened fetch:

- **HTTP(S) only**; URL scheme/userinfo validation.
- **Public-address pinning** — DNS results must resolve to public IPs (no RFC1918,
  loopback, link-local, metadata ranges); redirects are re-resolved and re-checked
  hop by hop. The validated addresses are installed in curl's DNS resolution table
  before connecting, while the original hostname remains in the URL for Host/TLS
  verification. Requests use fresh direct connections and bypass environment/session
  proxies so a second DNS lookup or proxy cannot redirect them to an unchecked address.
  The session's temporary curl options are serialized and restored after each request.
- **Same-host binding** — with `SCRAPER_REQUIRE_SAME_HOST=true` (default), the crawl
  (including redirects and CDN/API hops) must stay on the source's host. Adapters
  declare known secondary hosts explicitly (`allowed_hosts = ["api.example.com"]`);
  `SCRAPER_ALLOWED_HOST_OVERRIDES` exists for deployment-level exceptions — prefer the
  adapter-local list.
- **Response caps** — `SCRAPER_MAX_RESPONSE_MB` (8) and `SCRAPER_TIMEOUT_SECONDS` (30).
- **TLS-fingerprint-resistant client** — `curl-cffi` impersonation, because several
  target sites block vanilla HTTP clients.

Adversarial coverage: `novelwiki/eval/scraper_security_tests.py` and the provider-free
`tests/unit/modules/acquisition/test_scraper_dns_pinning.py` (including a real local curl
transport test, proxy bypass, and concurrent-session isolation).

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
  stored, `translation_status='pending'` until translated.
- New chapters make the codex *stale*, visible in the novel health panel; the next
  build extends it ([codex-build-and-ask.md](codex-build-and-ask.md)).
- Imported books register an import source and flow through the exact same
  `upsert_ingested_chapter` funnel ([file-import.md](file-import.md)).
