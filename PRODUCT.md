# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Readers managing webnovels and ebooks on a self-hosted instance, and administrators operating that instance. This product record is derived from the repository's living documentation; the redesign decisions were delegated by the project owner.

## Product Purpose

Tideglass brings web chapters and EPUB/PDF imports into a personal library with reading progress, translation, narration, and an optional spoiler-safe Codex.

## Operating Context

Readers return to ongoing stories on desktop and mobile, import books, browse shared books, and inspect background work. Administrators manage access, quotas, and service configuration.

## Capabilities and Constraints

- Preserve private/public/global novel visibility and per-reader progress.
- Codex information is bounded by server-observed chapter reads. Browser preferences must never unlock future knowledge.
- Translation, imports, narration, and extraction run through existing durable pipelines.
- Keep the React SPA, FastAPI API, same-origin authentication, and module boundaries.
- Represent loading, unavailable services, errors, and empty libraries honestly.

## Brand Commitments

The product name is Tideglass. No additional visual constraints were specified by the owner.

## Evidence on Hand

README.md and docs/ describe implemented workflows. Browser test fixtures provide explicitly synthetic stories for interface verification. No commercial or performance claims are authorized by those fixtures.

## Product Principles

- Make returning to a story effortless.
- Keep reading calm and operational details available when needed.
- Protect the reader's place and spoiler boundary.
- Give every failed action a clear recovery path.
