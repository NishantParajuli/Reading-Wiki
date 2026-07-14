"""Convenience entrypoint: launch the FastAPI app.

For ingestion use the CLI instead:  `python -m novelwiki.cli --help`
"""
import uvicorn

from novelwiki.platform.observability.logging import configure_logging


def main():
    configure_logging()
    uvicorn.run(
        "novelwiki.api.app:app", host="0.0.0.0", port=8000, reload=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
