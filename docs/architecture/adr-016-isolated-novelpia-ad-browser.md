# ADR 016: Isolate Novelpia ad completion from chapter extraction

Date: 2026-09-27

Status: accepted

## Context

Novelpia Global supports authenticated prose extraction through its reader API, but
some subscription plans require periodic browser ad completion. A valid account cookie
alone does not satisfy that requirement. Loading a full page executes third-party scripts
and contacts advertising hosts, which cannot inherit the scraper's same-host boundary.
The application also needs bounded jobs, cancellation, private account state, and resumable
chapter ingestion when browser interactions fail.

## Decision

- Acquisition keeps chapter parsing, access checks, ordering, and persistence in its
  HTTP adapter. Only recognized ad gates invoke the optional browser service, once per
  episode. A completed browser operation triggers fresh authentication and an independent
  API retry; the sidecar never supplies chapter text to Reading.
- A separate authenticated Node/Playwright service performs the site's normal countdown
  and Continue flow. It neither synthesizes reward requests nor changes timers. Paid
  unlocks remain explicit actions on Novelpia.
- Each request supplies the requesting user's already-validated cookies to a fresh
  browser context. No persistent browser profile or credential-bearing logs, traces,
  screenshots, or cookie artifacts are retained. Disconnect/deadline/shutdown closes
  the browser; one active request bounds resource consumption.
- The browser service sits on an internal network without direct Internet access. A
  separate CONNECT proxy validates public HTTPS destinations and connects to the validated
  address. Only that proxy joins the egress network. Browser/proxy ports are unpublished.
  Application-side URL checks supplement this network boundary rather than replace it.
- The feature is optional. Disabled or unavailable infrastructure, expired sessions,
  timeouts, and unresolved gates return actionable manual recovery without discarding
  already ingested chapters. Non-secret navigation checkpoints resume after the last
  saved episode without consuming another access attempt on that saved chapter.

## Consequences

The deployment gains two optional CPU services, a private service token, and independently
maintained browser/proxy images. Browser tests and proxy adversarial tests are required
alongside the API parser fixtures. Normal advertising behavior remains externally
controlled; successful representative checks do not guarantee unattended import of an
entire catalogue. The living [scraping pipeline](../pipelines/scraping.md),
[deployment](../operations/deployment.md#novelpia-ad-browser-optional), and
[private API](../api/novelpia-browser.md) describe current operating limits.
