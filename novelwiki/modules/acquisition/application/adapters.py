from .ports import ScraperAdapterCatalog


class ListScraperAdapters:
    def __init__(self, catalog: ScraperAdapterCatalog):
        self._catalog = catalog

    def list(self) -> list[dict]:
        return self._catalog.list_adapters()
