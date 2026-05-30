"""Convenience entrypoint: launch the FastAPI app.

For ingestion use the CLI instead:  `python -m novelwiki.cli --help`
"""
import uvicorn


def main():
    uvicorn.run("novelwiki.api.app:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
