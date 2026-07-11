from .scraper.adapters import list_adapters


class BuiltinScraperAdapterCatalog:
    def list_adapters(self) -> list[dict]:
        return list_adapters()
