"""Generic durable background jobs (scrape / codex build / translation).

`service` holds the job model + CRUD + quota finalization; `worker` is the DB-polled task that
claims and runs them. See novelwiki/jobs/service.py for the design overview.
"""
