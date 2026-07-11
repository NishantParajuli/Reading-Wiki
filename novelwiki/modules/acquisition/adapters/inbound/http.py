from fastapi import APIRouter, Depends

from ...application import ListScraperAdapters

router = APIRouter()


async def adapter_catalog_dependency() -> ListScraperAdapters:
    raise RuntimeError("ListScraperAdapters was not wired by the composition root")


@router.get("/adapters")
async def api_adapters(
    query: ListScraperAdapters = Depends(adapter_catalog_dependency),
):
    """The scraping techniques available for the Add-Source dropdown."""
    return query.list()
