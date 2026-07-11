from novelwiki.modules.acquisition.adapters.outbound.adapter_catalog import (
    BuiltinScraperAdapterCatalog,
)
from novelwiki.modules.acquisition.application import ListScraperAdapters


def build_adapter_catalog_query() -> ListScraperAdapters:
    return ListScraperAdapters(BuiltinScraperAdapterCatalog())
