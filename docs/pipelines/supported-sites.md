# Supported website sources

Each source selects one adapter key. Use that key with **Add novel**, **Manage → Add
source**, the source HTTP APIs, or CLI `add-novel --adapter KEY`. The live registry is
`GET /api/adapters`; it returns `name`, `label`, `requires`, `default_language`, and
`start_url_hint`. Registry presence means an extractor is implemented, not that every
page on that external site is currently reachable.

## URL and language reference

Paths below are shapes, not literal sample books. Copy an actual URL from the selected
website. A novel/catalogue start works only where explicitly listed; the other adapters
start at the first chapter you want to collect.

| Adapter key | Website | Accepted start | Default language | Extraction notes |
|---|---|---|---|---|
| `fenrirealm` | `fenrirealm.com` | `/series/{slug}/{number}` or `/series/{slug}/chapter-{number}` | `en` | Published chapter data or reader HTML; follows next navigation. |
| `readhive` | `readhive.org` | `/series/{id}/{number}/` | `en` | Reader prose and next link when available; numeric paths can supply a next-URL fallback. |
| `boti-translations` | `botitranslation.com` | `/chapter/{id}` or `/chapter/{id}-{title}` | `en` | Public chapter API on `api.mystorywave.com`; follows its next chapter ID. |
| `69shuba` | `69shuba.com` | `/txt/{book-id}/{chapter-id}` | `zh` | Declared charset, UTF-8, or GB18030 decoding; preserves HTTPS. IDs are not reading ordinals. |
| `wetriedtls` | `wetriedtls.com` | `/series/{slug}/chapter-{number}` | `en` | Published Next.js chapter data; follows the next chapter slug and handles chapter 0. |
| `novel543` | `novel543.com` | `/{book-id}/{group}_{chapter}.html`, starting at the first part | `zh` | Consecutive split pages such as `_1_2.html` are joined before saving one chapter. |
| `dreamy-translations` | `dreamy-translations.com` | `/novel/{slug}` or `/novel/{slug}/chapter/{number}` | `en` | Public server-rendered reader. |
| `penguin-squad` | `penguin-squad.com` | `/novels/{slug}` or `/novels/{slug}/chapter-{number}-{title}` | `en` | Public server-rendered reader; use the complete chapter slug. |
| `azurechronicles` | `azurechronicles.com` | `/novel/{slug}/` or `/novel/{slug}/chapter-{number}/` | `en` | Public server-rendered reader. |
| `fucknovelpia` | `fucknovelpia.com` | `/novel/{slug}`, `/novel.php?slug=…`, or `/chapter.php?hash={40-character-hex}&ch={number}` | `en` | Current PHP catalogue/reader; follows the same book's published next link. Old WordPress URLs are not supported. |
| `raw-fucknovelpia` | `raw-fucknovelpia.com` | `/novel/{slug}` or `/novel.php?slug=…` | `ko` | Catalogue ZIP download containing EPUB, TXT, or HTML; requires the archive password in the web form. |

For Dreamy, Penguin Squad, and Azure Chronicles, a novel page resolves its published
reading link or lowest numbered chapter link. Chapter navigation stays within the same
novel and follows explicit next links; it does not guess hidden chapter URLs. A lock
is recognized from the site's access metadata or explicit lock UI. Missing reader text
is an error, not proof of a premium wall or a successfully completed crawl.

The source's **language** describes the fetched text, not necessarily the language of
the original work. The web forms apply adapter defaults and initially enable **Raw
(needs translation)** for a non-English default. Readers can override both before saving.
The HTTP and CLI defaults remain `en` / `is_raw=false`; direct callers must explicitly
send the desired values, or use `--lang zh --raw` / `--lang ko --raw` in the CLI.

## FuckNovelpia readers and raw archives

The English reader adapter starts from a current catalogue or chapter page. It preserves
the reader's `ch` number, including fractions, skips image-only reader entries, and checks
that each next link advances within the selected book. Saved chapter URLs contain `hash`
and `ch`; temporary navigation signatures are discarded so checkpoints remain reusable.
Missing or empty readers fail the scrape instead of recording a successful empty book.

The raw site is an archive catalogue. Select **FuckNovelpia RAW archives**, paste the
novel's catalogue URL, enter its **ZIP password**, and check **Language** and **Raw**.
The `ko` default can be changed for Chinese, Japanese, or English books. Use the catalogue
URL instead of copying the temporary download link. Each run obtains that link afresh,
then follows its checked redirect to `assets.raw-fucknovelpia.com`.

For API callers, supply `config: {"archive_password": "YOUR_ARCHIVE_PASSWORD"}` inside
the source payload. The current `add-novel` CLI has no source-config option, so use the
web form or HTTP API to create an encrypted archive source. The password is persisted
in `sources.config` JSONB and is not embedded in chapter URLs or text. The novel-detail
source response omits `config`. No default archive password is built into the application.
To correct a password, open **Manage → Edit source → New ZIP password**. Leaving the
field blank keeps the existing password; the form never displays the stored value.
API callers can PATCH `{"config":{"archive_password":"NEW_ARCHIVE_PASSWORD"}}` to
the source endpoint. Config updates merge supplied keys rather than replacing other
source settings. The password must be a string; an API update with
`{"config":{"archive_password":""}}` clears it. Configuration must be valid JSON with
finite numbers and valid Unicode, and cannot contain null characters. Invalid config or
source text returns `422` before a source update can renumber chapters or change settings.

Extraction stays in memory: archive paths are never unpacked to disk. EPUB text follows
its spine and narrative segmentation; NCX/EPUB3 table-of-contents labels supply missing
chapter headings, and a leading page containing only the exact book title is skipped.
TXT uses recognized chapter headings where present;
HTML uses prose paragraphs. Archive members are sorted naturally by filename. The adapter
assigns source-local numbers by the resulting prose order, starting at 1; they need not
match numbers printed in a book's headings. Unrecognized front matter or an alternate
title page can remain a reading section, so local index 1 is not guaranteed to be the
story's first numbered chapter. Checkpoints use
`/novel/{slug}#tideglass-chapter=N`. A later run downloads the archive again and resumes
from that section. Reordered or replaced archive contents can change what those positions
mean; inspect the source before forcing a refresh over existing chapters.

Archive limits are 10,000 entries, 128 MiB total expanded size, and 64 MiB per member;
the same checks apply inside nested EPUBs, and extracted text is capped at 128 MiB.
The network response still obeys `SCRAPER_MAX_RESPONSE_MB` (8 MiB by default). Unsafe
paths and symlinks are rejected. Only ZIP/EPUB archives and EPUB/TXT/HTML/XHTML members
are handled. Unsupported encryption, a wrong password, damaged archives, and absent
readable prose report errors. Images are not imported by this adapter and OCR is not run;
use the file-import workflow for scanned material.

## Crawl limits and recovery

- `max_chapters` in HTTP or `--max` in the CLI bounds a scrape run and must be positive.
  When scraping all sources of a novel, the bound applies independently to each source.
- A normal resume reopens the last stored chapter URL to discover its current next
  link. The runner allows that checkpoint in addition to the requested chapter limit,
  so `--max 1` can advance by one new chapter. `--force` starts again from the configured
  start URL and allows existing text to be updated. Source-local numbers plus
  `chapter_offset` determine global numbers.
- Empty text, non-finite numbers, or repeated/backward chapter numbers are rejected.
  An unnumbered first run can assign sequential local numbers; an unnumbered resume
  fails instead of overwriting an earlier chapter under a guessed number. Unknown
  adapter keys fail instead of silently using another website's extractor.
- Fetches stay behind the same SSRF boundary as the rest of Acquisition: public DNS
  addresses, checked redirects, adapter-declared host exceptions, response-size caps,
  and timeouts. See [scraping](scraping.md) and
  [scraper configuration](../operations/configuration.md#scraper).
- Authentication-only and premium text are outside the public-page adapters. Buying a
  chapter in a browser does not transfer that browser's logged-in session to Tideglass.

## Check a source without importing it

Run the diagnostic from the repository root:

```bash
uv run python try_adapter.py readhive "https://readhive.org/series/201561/69" --max 2
```

It uses the configured safe-fetch host/DNS checks and delay, prints only chapter numbers,
titles, and character counts, and does not create jobs or save chapter text. `--max`
defaults to 2 and must be positive. Fetch/parse failures exit 1; a recognized premium
boundary stops cleanly. Argument errors exit 2.

For an encrypted archive, provide the password through an environment variable already
set in your shell and pass its **name**, not its value:

```bash
uv run python try_adapter.py raw-fucknovelpia "https://raw-fucknovelpia.com/novel/BOOK_SLUG" \
  --max 2 --archive-password-env TIDEGLASS_ARCHIVE_PASSWORD
```

Replace `BOOK_SLUG` with the actual book slug. An unset or empty password variable exits
2. This diagnostic does not consume AI-provider quota and does not require a database.

## Verification scope

Parser and navigation regression tests use local fixtures and require no source account.
Live checks exercise representative public pages and bounded crawls. They establish
behavior for those pages at the time of checking, not an availability guarantee for a
site's complete catalogue. A changed layout, unavailable hostname, rate limit, or access
challenge can require an adapter update even when the registry entry is present.

During the September 2026 expansion, the real safe-fetch crawl for each new English
translation adapter yielded chapters 1 and 2 from a public novel page: Dreamy's `babya`,
Penguin Squad's `romelia-war-chronicle`, and Azure's `sandmancer-of-the-scorched-desert`.
Public lock pages were also inspected. Provider-free fixtures cover non-sequential
navigation, chapter ordering, absent content, and explicit access locks. No account-only
chapter acquisition was verified.

The original adapters were also checked against live chapters: FenriRealm
`absolute-regression` chapters 1–2, Readhive series `201561` chapters 69–70,
Boti chapter IDs `1620667` → `1620669` (reading
chapters 23–24), WeTriedTLS `regression-is-too-much` chapters 0–1, 69shuba book `31604`
chapter IDs `22525886` → `22525888`, and Novel543 book `0523507892` chapters 1–2,
including each chapter's second page. These were bounded checks, not complete-book crawls.

Some individual URLs were unavailable even though their adapters passed on other books:
Readhive's older `/series/20966/1/` yielded chapter 1, but its predicted chapter-2 paths
returned 404. For the shared HTML crawl loop, a 404/410 from a guessed next URL ends the
crawl; failures on explicit chapter links remain errors. Use the diagnostic to distinguish
the book/URL being unavailable from an extraction regression.

FuckNovelpia's `it-s-not-swordsmanship-it-s-a-bug` catalogue yielded site indices 2
and 3 after skipping the image-only index 1. The RAW
`cultivating-in-a-xianxia-with-a-dragon-heart-unknown` catalogue successfully downloaded
and unlocked its encrypted ZIP using a supplied password. A bounded extraction of the
download retained an alternate title page followed by Episodes 1 and 2; resuming at
section 2 reproduced the same two episode sections. These checks verify the archive path
and initial sections, not every chapter in the downloaded book. Regression fixtures use
synthetic prose and a separate public test password, never downloaded chapter text or
live source passwords.
