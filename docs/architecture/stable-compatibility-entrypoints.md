# Stable compatibility entrypoints

Internal business-module code and Bootstrap wiring use canonical module and Platform
paths. The remaining old namespaces are passive external import aliases or dependency-injecting
wrappers only; they hold no business workflow.

| Stable path/category | External consumer and reason |
|---|---|
| `novelwiki.api.app:app` | ASGI deployment contract |
| `novelwiki.cli` | `python -m novelwiki.cli` and installed CLI contract |
| `novelwiki.agy.worker` | Dedicated host-worker systemd/process contract |
| `novelwiki.api.routes` | Original evaluation fixtures and downstream direct-call fixtures; delegates through normal composed services and performs no private mutation |
| `novelwiki.api.routes_product`, `routes_tts`, `admin_routes` | Original evaluation fixture imports |
| `novelwiki.auth.*`, `novelwiki.quota` | Authentication/quota fixture and downstream Python imports |
| `novelwiki.jobs.*` | Durable-job fixture and operational script imports |
| `novelwiki.agy.*`, `novelwiki.ai_backend.*`, `novelwiki.ai_limits` | Dedicated worker, policy fixture, and AGY plugin-facing imports |
| `novelwiki.importer.*`, `novelwiki.scraper.*` | Import/scraper evaluation and operational script imports |
| `novelwiki.ingest.*`, `novelwiki.retrieval.*`, `novelwiki.agent.*` | Codex evaluation and operational script imports |
| `novelwiki.translate.*`, `novelwiki.tts.*` | Translation/narration evaluation and operational script imports |
| `novelwiki.audit`, `novelwiki.config.settings`, `novelwiki.db.connection` | Platform compatibility for downstream scripts; schema/migration modules remain explicit database entrypoints |

These aliases may be imported by tests and external callers. Architecture enforcement
fails if a business module uses them for internal communication.
