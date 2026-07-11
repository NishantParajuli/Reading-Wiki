from collections.abc import Callable

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from novelwiki.auth.deps import current_user, require_admin
from novelwiki.config.settings import settings
from novelwiki.kernel.errors import (
    Conflict, Forbidden, NotFound, QuotaExceeded, ValidationFailed,
)
from novelwiki.modules.acquisition.public import SourceDraft
from novelwiki.modules.identity.public import Principal

from ...application import (
    AcquisitionService, ImportRequestError, ImportService, ListScraperAdapters,
    ScheduleScrape,
)

router = APIRouter()


async def adapter_catalog_dependency() -> ListScraperAdapters:
    raise RuntimeError("ListScraperAdapters was not wired by the composition root")


async def acquisition_service_dependency() -> AcquisitionService:
    raise RuntimeError("AcquisitionService was not wired by the composition root")


async def import_service_dependency() -> ImportService:
    raise RuntimeError("ImportService was not wired by the composition root")


async def acquisition_principal_factory_dependency() -> Callable[[dict], Principal]:
    raise RuntimeError("Acquisition principal factory was not wired by the composition root")


class SourceCreate(BaseModel):
    adapter: str
    start_url: str
    language: str = "en"
    is_raw: bool = False
    chapter_offset: float = 0
    label: str | None = None
    config: dict | None = None


class SourceUpdate(BaseModel):
    chapter_offset: float | None = None
    start_url: str | None = None
    label: str | None = None
    language: str | None = None
    is_raw: bool | None = None


class ScrapeTrigger(BaseModel):
    force: bool = False
    max_chapters: int | None = None
    source_id: int | None = None


class PlanUpdate(BaseModel):
    plan: dict


class ImportCommit(BaseModel):
    mode: str = "new"
    novel_id: int | None = None
    source_id: int | None = None
    offset: float = 0
    is_raw: bool | None = None


class OcrConfirm(BaseModel):
    gemini_first: bool = False


class ImportInit(BaseModel):
    filename: str
    size: int = 0


class ImportBatch(BaseModel):
    path: str | None = None
    recursive: bool = True
    auto_commit: bool = False
    group_series: bool = False


class CommitSeries(BaseModel):
    job_ids: list[int]


def _raise_http(exc: Exception) -> None:
    status = (
        404
        if isinstance(exc, NotFound)
        else 403
        if isinstance(exc, Forbidden)
        else 409
        if isinstance(exc, Conflict)
        else 422
    )
    raise HTTPException(status_code=status, detail=str(exc)) from exc


def _raise_import_http(exc: Exception) -> None:
    if isinstance(exc, ImportRequestError):
        raise HTTPException(
            status_code=exc.status_code, detail=exc.detail, headers=exc.headers,
        ) from exc
    status = (
        404 if isinstance(exc, NotFound)
        else 403 if isinstance(exc, Forbidden)
        else 429 if isinstance(exc, QuotaExceeded)
        else 409 if isinstance(exc, Conflict)
        else 422
    )
    raise HTTPException(status_code=status, detail=str(exc)) from exc


async def _import_dependencies(service, principal_factory):
    if not isinstance(service, ImportService):
        from novelwiki.bootstrap.acquisition_routes import build_import_service
        service = await build_import_service()
    if not callable(principal_factory):
        from novelwiki.bootstrap.acquisition_routes import (
            build_acquisition_principal_factory,
        )
        principal_factory = build_acquisition_principal_factory()
    return service, principal_factory


async def _read_limited_request_body(request: Request, max_bytes: int) -> bytes:
    data = bytearray()
    async for chunk in request.stream():
        if not chunk:
            continue
        data.extend(chunk)
        if len(data) > max_bytes:
            raise HTTPException(status_code=413, detail="Chunk too large.")
    return bytes(data)


def _asset_headers() -> dict[str, str]:
    return {
        "Cache-Control": "private, max-age=3600",
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": (
            "default-src 'none'; img-src 'self' data:; object-src 'none'; "
            "script-src 'none'; sandbox"
        ),
    }


@router.get("/adapters")
async def api_adapters(
    query: ListScraperAdapters = Depends(adapter_catalog_dependency),
):
    """The scraping techniques available for the Add-Source dropdown."""
    return query.list()


@router.post("/novels/{novel_id}/sources")
async def api_add_source(
    novel_id: int,
    payload: SourceCreate,
    user: dict = Depends(current_user),
    service: AcquisitionService = Depends(acquisition_service_dependency),
):
    try:
        source_id = await service.add_source(
            novel_id,
            Principal.from_user(user),
            SourceDraft(**payload.model_dump()),
        )
    except (NotFound, Forbidden, Conflict, ValidationFailed) as exc:
        _raise_http(exc)
    return {"id": source_id}


@router.patch("/novels/{novel_id}/sources/{source_id}")
async def api_update_source(
    novel_id: int,
    source_id: int,
    payload: SourceUpdate,
    user: dict = Depends(current_user),
    service: AcquisitionService = Depends(acquisition_service_dependency),
):
    """Edits an existing source. Changing `chapter_offset` also renumbers that source's
    already-scraped chapters onto the new global numbering (e.g. set -1 when a raw source
    is one chapter ahead of the translation), so the fix is immediate — no re-scrape."""
    try:
        status, renumbered = await service.update_source(
            novel_id,
            source_id,
            Principal.from_user(user),
            payload.model_dump(exclude_unset=True),
        )
    except (NotFound, Forbidden, Conflict, ValidationFailed) as exc:
        _raise_http(exc)
    if status == "noop":
        return {"status": "noop"}
    return {"status": "success", "renumbered": renumbered}


@router.post("/novels/{novel_id}/scrape")
async def api_scrape(
    novel_id: int,
    payload: ScrapeTrigger,
    user: dict = Depends(current_user),
    service: AcquisitionService = Depends(acquisition_service_dependency),
):
    """Schedules a durable scrape job (survives restarts). Targets one source if source_id is
    given, else every source of the novel. Repeated clicks for the same target dedupe onto the
    already-active job rather than piling up duplicate work."""
    try:
        return await service.schedule_scrape(
            novel_id,
            Principal.from_user(user),
            ScheduleScrape(**payload.model_dump()),
        )
    except (NotFound, Forbidden, Conflict, ValidationFailed) as exc:
        _raise_http(exc)


@router.get("/assets/novels/{novel_id}/{filename}")
async def api_novel_asset(
    novel_id: int,
    filename: str,
    user: dict = Depends(current_user),
    service: AcquisitionService = Depends(acquisition_service_dependency),
):
    """Serve a committed imported image only if the caller can read the novel."""
    try:
        asset = await service.novel_asset(
            novel_id, filename, Principal.from_user(user)
        )
    except (NotFound, Forbidden, Conflict, ValidationFailed) as exc:
        _raise_http(exc)
    return FileResponse(asset.path, media_type=asset.mime, headers=_asset_headers())


@router.get("/assets/import-jobs/{job_id}/{filename}")
async def api_import_job_asset(
    job_id: int,
    filename: str,
    user: dict = Depends(current_user),
    service: AcquisitionService = Depends(acquisition_service_dependency),
):
    """Serve a staged import preview image only to the job owner or an admin."""
    try:
        asset = await service.import_job_asset(
            job_id, filename, Principal.from_user(user)
        )
    except (NotFound, Forbidden, Conflict, ValidationFailed) as exc:
        _raise_http(exc)
    return FileResponse(asset.path, media_type=asset.mime, headers=_asset_headers())


@router.post("/import/upload")
async def api_import_upload(
    file: UploadFile = File(...), user: dict = Depends(current_user),
    service: ImportService = Depends(import_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        acquisition_principal_factory_dependency
    ),
):
    """Accept an uploaded EPUB, stash it under a fresh job id, and queue it for parsing."""
    service, principal_factory = await _import_dependencies(service, principal_factory)
    try:
        return await service.upload(file, principal_factory(user))
    except (ImportRequestError, NotFound, Forbidden, Conflict, QuotaExceeded) as exc:
        _raise_import_http(exc)


@router.post("/import/scan-incoming")
async def api_import_scan_incoming(
    user: dict = Depends(require_admin),
    service: ImportService = Depends(import_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        acquisition_principal_factory_dependency
    ),
):
    """Enqueue any EPUB/PDF dropped into IMPORT_INCOMING_DIR (the watched-folder path for big
    files that bypass the multipart upload cap). Non-recursive, manual review per book."""
    service, principal_factory = await _import_dependencies(service, principal_factory)
    try:
        return await service.scan_incoming(principal_factory(user))
    except (ImportRequestError, NotFound, Forbidden, Conflict, QuotaExceeded) as exc:
        _raise_import_http(exc)


@router.post("/import/batch")
async def api_import_batch(
    payload: ImportBatch, user: dict = Depends(require_admin),
    service: ImportService = Depends(import_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        acquisition_principal_factory_dependency
    ),
):
    """Bulk-import a folder (e.g. a Calibre library). Recurses by default, can auto-commit
    each book without review, and can group EPUB volumes of one series into a single novel."""
    service, principal_factory = await _import_dependencies(service, principal_factory)
    try:
        return await service.batch(
            principal_factory(user), path=payload.path, recursive=payload.recursive,
            auto_commit=payload.auto_commit, group_series=payload.group_series,
        )
    except (ImportRequestError, NotFound, Forbidden, Conflict, QuotaExceeded) as exc:
        _raise_import_http(exc)


@router.post("/import/upload/init")
async def api_import_upload_init(
    payload: ImportInit, user: dict = Depends(current_user),
    service: ImportService = Depends(import_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        acquisition_principal_factory_dependency
    ),
):
    service, principal_factory = await _import_dependencies(service, principal_factory)
    try:
        return await service.upload_init(
            payload.filename, payload.size, principal_factory(user)
        )
    except (ImportRequestError, NotFound, Forbidden, Conflict, QuotaExceeded) as exc:
        _raise_import_http(exc)


@router.get("/import/upload/{job_id}/status")
async def api_import_upload_status(
    job_id: int, user: dict = Depends(current_user),
    service: ImportService = Depends(import_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        acquisition_principal_factory_dependency
    ),
):
    service, principal_factory = await _import_dependencies(service, principal_factory)
    try:
        return await service.upload_status(job_id, principal_factory(user))
    except (ImportRequestError, NotFound, Forbidden, Conflict, QuotaExceeded) as exc:
        _raise_import_http(exc)


@router.put("/import/upload/{job_id}/chunk")
async def api_import_upload_chunk(
    job_id: int, request: Request, user: dict = Depends(current_user),
    service: ImportService = Depends(import_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        acquisition_principal_factory_dependency
    ),
):
    """Append one chunk at the byte offset given in the `Upload-Offset` header.

    The chunk must start exactly at the current resume cursor (contiguous, append-only), fit
    the per-chunk cap, and not push the running total past the declared size — so a client
    can't punch gaps, forge a sparse file, or blow past the size committed to at init. A stale
    offset gets a 409 carrying the real cursor so the client can resync; a chunk that re-sends
    already-received bytes is an idempotent no-op only when those bytes actually match what's
    stored. Every accepted chunk bumps the session's `updated_at` so an upload still in progress
    isn't read as abandoned by the cleanup sweep."""
    data = await _read_limited_request_body(
        request, settings.UPLOAD_CHUNK_MAX_MB * 1024 * 1024,
    )
    service, principal_factory = await _import_dependencies(service, principal_factory)
    try:
        return await service.upload_chunk(
            job_id, request.headers.get("Upload-Offset", "0"), data,
            principal_factory(user),
        )
    except (ImportRequestError, NotFound, Forbidden, Conflict, QuotaExceeded) as exc:
        _raise_import_http(exc)


@router.post("/import/upload/{job_id}/complete")
async def api_import_upload_complete(
    job_id: int, user: dict = Depends(current_user),
    service: ImportService = Depends(import_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        acquisition_principal_factory_dependency
    ),
):
    service, principal_factory = await _import_dependencies(service, principal_factory)
    try:
        return await service.upload_complete(job_id, principal_factory(user))
    except (ImportRequestError, NotFound, Forbidden, Conflict, QuotaExceeded) as exc:
        _raise_import_http(exc)


@router.post("/import/commit-series")
async def api_import_commit_series(
    payload: CommitSeries, user: dict = Depends(current_user),
    service: ImportService = Depends(import_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        acquisition_principal_factory_dependency
    ),
):
    """Fold several parsed jobs into one multi-volume novel (ordered by series index)."""
    service, principal_factory = await _import_dependencies(service, principal_factory)
    try:
        return await service.commit_series(payload.job_ids, principal_factory(user))
    except (ImportRequestError, NotFound, Forbidden, Conflict, QuotaExceeded) as exc:
        _raise_import_http(exc)


@router.get("/import/jobs")
async def api_import_jobs(
    user: dict = Depends(current_user),
    service: ImportService = Depends(import_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        acquisition_principal_factory_dependency
    ),
):
    service, principal_factory = await _import_dependencies(service, principal_factory)
    return await service.list_jobs(principal_factory(user))


@router.get("/import/jobs/{job_id}")
async def api_import_job(
    job_id: int, user: dict = Depends(current_user),
    service: ImportService = Depends(import_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        acquisition_principal_factory_dependency
    ),
):
    service, principal_factory = await _import_dependencies(service, principal_factory)
    try:
        return await service.get_job(job_id, principal_factory(user))
    except (ImportRequestError, NotFound, Forbidden, Conflict, QuotaExceeded) as exc:
        _raise_import_http(exc)


@router.put("/import/jobs/{job_id}/plan")
async def api_import_update_plan(
    job_id: int, payload: PlanUpdate, user: dict = Depends(current_user),
    service: ImportService = Depends(import_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        acquisition_principal_factory_dependency
    ),
):
    """Replace the editable segmentation plan (merge/split/rename/include/number/kind are
    all client-side edits that produce a new plan). Block ranges are validated against the
    stored block stream so a bad edit can't point off the end of the document."""
    service, principal_factory = await _import_dependencies(service, principal_factory)
    try:
        return await service.update_plan(
            job_id, payload.plan, principal_factory(user)
        )
    except (ImportRequestError, NotFound, Forbidden, Conflict, QuotaExceeded) as exc:
        _raise_import_http(exc)


@router.post("/import/jobs/{job_id}/commit")
async def api_import_commit(
    job_id: int, payload: ImportCommit, user: dict = Depends(current_user),
    service: ImportService = Depends(import_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        acquisition_principal_factory_dependency
    ),
):
    """Hand the job to the worker for commit: stamp the target into options and flip the
    status to 'committing'. The worker writes chapters via the scraper persist path."""
    service, principal_factory = await _import_dependencies(service, principal_factory)
    try:
        return await service.commit(
            job_id, principal_factory(user), mode=payload.mode,
            novel_id=payload.novel_id, source_id=payload.source_id,
            offset=payload.offset, is_raw=payload.is_raw,
        )
    except (ImportRequestError, NotFound, Forbidden, Conflict, QuotaExceeded) as exc:
        _raise_import_http(exc)


@router.post("/import/jobs/{job_id}/confirm-ocr")
async def api_import_confirm_ocr(
    job_id: int, payload: OcrConfirm, user: dict = Depends(current_user),
    service: ImportService = Depends(import_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        acquisition_principal_factory_dependency
    ),
):
    """Approve the (expensive) OCR run for a scanned PDF: the job leaves the confirm gate and
    the worker starts reading pages (sidecar + Gemini escalation, budget-guarded)."""
    service, principal_factory = await _import_dependencies(service, principal_factory)
    try:
        return await service.confirm_ocr(
            job_id, payload.gemini_first, principal_factory(user)
        )
    except (ImportRequestError, NotFound, Forbidden, Conflict, QuotaExceeded) as exc:
        _raise_import_http(exc)


@router.post("/import/jobs/{job_id}/cancel")
async def api_import_cancel(
    job_id: int, user: dict = Depends(current_user),
    service: ImportService = Depends(import_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        acquisition_principal_factory_dependency
    ),
):
    service, principal_factory = await _import_dependencies(service, principal_factory)
    try:
        return await service.cancel(job_id, principal_factory(user))
    except (ImportRequestError, NotFound, Forbidden, Conflict, QuotaExceeded) as exc:
        _raise_import_http(exc)


@router.delete("/import/jobs/{job_id}")
async def api_import_delete(
    job_id: int, user: dict = Depends(current_user),
    service: ImportService = Depends(import_service_dependency),
    principal_factory: Callable[[dict], Principal] = Depends(
        acquisition_principal_factory_dependency
    ),
):
    """Delete a job row and free its scratch dir + staged assets."""
    service, principal_factory = await _import_dependencies(service, principal_factory)
    try:
        return await service.delete(job_id, principal_factory(user))
    except (ImportRequestError, NotFound, Forbidden, Conflict, QuotaExceeded) as exc:
        _raise_import_http(exc)
