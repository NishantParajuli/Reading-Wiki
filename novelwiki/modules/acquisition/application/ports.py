from typing import Protocol


class ScraperAdapterCatalog(Protocol):
    def list_adapters(self) -> list[dict]: ...
