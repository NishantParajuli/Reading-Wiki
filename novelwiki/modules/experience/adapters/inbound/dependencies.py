async def operational_projection_dependency():
    raise RuntimeError("Operational projections were not wired by the composition root")


async def quota_projection_dependency():
    raise RuntimeError("Identity quota projection was not wired by the composition root")
