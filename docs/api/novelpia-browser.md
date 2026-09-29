# Private Novelpia browser API

This is the optional internal service on port **8079**, implemented in
`sidecar-novelpia/server.mjs` and `browser.mjs`. It is not mounted under the web app's
`/api` and does not add public HTTP routes or use Tideglass browser sessions. Deployment
and its network boundary are documented in [deployment](../operations/deployment.md#novelpia-ad-browser-optional)
and [security](../operations/security.md#novelpia-ad-browser).

## Authentication and endpoints

`GET /health` returns `200 {"status":"ok"}` without authentication. It indicates that
the service is listening, not that a Novelpia session, ad, or browser launch has succeeded.

`POST /unlock` requires `X-Tideglass-Sidecar-Token`, matching `NOVELPIA_BROWSER_TOKEN`
or its `SIDECAR_AUTH_TOKEN` fallback. Startup rejects a missing token or one outside
24–4096 characters. There is no unauthenticated development bypass. Requests must use
`Content-Type: application/json` and fit within **64 KiB**.

The request contains:

| Field | Contract |
|---|---|
| `episode_id` | Positive safe integer; the service constructs the exact official `/viewer/{id}` URL. Caller-supplied arbitrary URLs are not accepted. |
| `cookies` | At most 12 normalized login-cookie objects with `name`, `value`, `domain`, root `path`, and optional epoch-second `expires` (null/omitted means a session cookie); `TKEY` is required. |
| `timeout_seconds` | Optional duration from 1 second through the service maximum (default 75, at most 90); the web setting validates 15–90 seconds. |

Only `TKEY`, `LOGINKEY`, and `USERKEY` are accepted, on `.novelpia.com`,
`novelpia.com`, `global.novelpia.com`, or `api-global.novelpia.com`; each value is capped
at 8 KiB.
Malformed cookies or an expired required `TKEY` fail validation; expired optional
`LOGINKEY`/`USERKEY` entries are skipped. Each request opens a fresh context; no
cookie values, chapter prose, or replacement session tokens appear in the response.

Every response is a small `{"status":"…"}` object with `Cache-Control: no-store`:

| HTTP | Status | Meaning |
|---|---|---|
| 200 | `completed` | The browser observed a successful normal ad grant or readable chapter response; the caller must independently verify API access. |
| 200 | `login_required` | The browser detected a login requirement. Replace the account cookies. |
| 400 | `invalid` | Malformed request or unsupported body type. |
| 401 | `unauthorized` | Missing or incorrect service token. |
| 404 | `not_found` | Unsupported authenticated method/path. |
| 413 | `invalid` | Body exceeds 64 KiB. |
| 429 | `busy` | Another browser operation is active. No second context is started. |
| 503 | `unavailable` | Browser/proxy/page operation could not complete. |
| 504 | `timeout` | Attempt deadline elapsed. |

## Operation and cancellation

Only one browser operation runs at a time. The application retries a busy response for
at most 30 seconds and reports **Waiting for Novelpia browser**. During the attempt it
reports **Watching Novelpia ad**. Browser work, including loading the page, is bounded
by the request deadline; the service also bounds body reading and request lifetime.
Client disconnection or process shutdown aborts active work and closes the browser.
The active slot stays occupied during cleanup. If Chromium remains open five seconds
after a disconnect/deadline, a cleanup watchdog exits the sidecar so the container
restart policy can recover it.

The sidecar visits only the requested main-frame viewer page, waits for its normal
countdown, and clicks its visible, enabled **Continue** button. It does not change timers,
click advertisements, call reward endpoints itself, or purchase chapters. Popups,
downloads, service workers, and navigation away from that viewer are blocked. Page
response inspection only detects completion; chapter extraction stays in the HTTP
scraper, which refreshes the access token and retries the episode independently.

The Playwright browser requires `NOVELPIA_BROWSER_PROXY` (Compose sets
`http://novelpia-egress:8899`) and uses that public-only CONNECT proxy. Cookie state
is request-local; there are no persistent profile, recording, tracing, or cookie-export
artifacts. Service responses/errors do not echo request bodies or site responses.
