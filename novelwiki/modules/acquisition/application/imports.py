from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from typing import Any

from novelwiki.kernel.errors import NotFound
from novelwiki.modules.identity.public import Principal

from .ports import CatalogAccessPort, ImportGateway, SpendPolicyPort

IMPORT_FORMATS = {".epub": "epub", ".pdf": "pdf"}


class ImportRequestError(Exception):
    def __init__(self, status_code: int, detail: str, headers: dict[str, str] | None = None):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.headers = headers


@dataclass(frozen=True)
class ImportConfig:
    incoming_dir: str
    max_upload_bytes: int
    max_upload_mb: int
    max_chunked_bytes: int
    max_chunked_upload_mb: int


def job_view(job: dict) -> dict:
    return {
        "id": int(job["id"]),
        "novel_id": int(job["novel_id"]) if job.get("novel_id") is not None else None,
        "format": job["format"], "status": job["status"], "stage": job.get("stage"),
        "filename": os.path.basename(job.get("original_path") or "") or None,
        "detected_meta": job.get("detected_meta") or {}, "plan": job.get("plan"),
        "stats": job.get("stats") or {}, "cost_estimate": job.get("cost_estimate"),
        "progress": job.get("progress") or {}, "options": job.get("options") or {},
        "error": job.get("error"),
        "created_at": job["created_at"].isoformat() if job.get("created_at") else None,
        "updated_at": job["updated_at"].isoformat() if job.get("updated_at") else None,
    }


class ImportService:
    def __init__(self, gateway: ImportGateway, catalog: CatalogAccessPort,
                 quota: SpendPolicyPort, config: ImportConfig):
        self._gateway = gateway
        self._catalog = catalog
        self._quota = quota
        self._config = config

    async def _own_job(self, job_id: int, principal: Principal) -> dict:
        job = await self._gateway.get_job(job_id)
        if not job or (not principal.is_admin and job.get("user_id") != principal.user_id):
            raise NotFound("Import job not found.")
        return job

    @staticmethod
    def _format(filename: str) -> tuple[str, str]:
        extension = os.path.splitext(filename or "")[1].lower()
        format = IMPORT_FORMATS.get(extension)
        if not format:
            raise ImportRequestError(400, "Only .epub and .pdf files are supported.")
        return extension, format

    async def upload(self, upload, principal: Principal) -> dict:
        self._quota.ensure_allowed(principal)
        extension, format = self._format(upload.filename or "")
        job_id = await self._gateway.create_job(
            format, original_path="", status="receiving", user_id=principal.user_id
        )
        try:
            path, sha256, size = await self._gateway.save_upload(
                job_id, upload, extension, self._config.max_upload_bytes
            )
            if size <= 0:
                raise ImportRequestError(400, "Uploaded file is empty.")
        except ValueError:
            await self._gateway.delete_job(job_id)
            self._gateway.cleanup_job(job_id)
            raise ImportRequestError(
                413, f"File exceeds the {self._config.max_upload_mb} MB upload cap."
            )
        except ImportRequestError:
            await self._gateway.delete_job(job_id)
            self._gateway.cleanup_job(job_id)
            raise
        await self._gateway.update_job(
            job_id, original_path=str(path), file_sha256=sha256, status="uploaded"
        )
        duplicates = await self._gateway.duplicate_imports(sha256, job_id)
        return {"id": job_id, "status": "uploaded", "format": format,
                "duplicate_of": duplicates}

    async def _enqueue_batch(self, files, *, auto_commit: bool, group_series: bool,
                             user_id: int) -> tuple[str, list[dict]]:
        self._gateway.ensure_dirs()
        batch_id = uuid.uuid4().hex
        options = {"batch_id": batch_id, "auto_commit": auto_commit,
                   "group_series": group_series}
        queued = []
        for source, name in files:
            extension, format = self._format(name)
            job_id = await self._gateway.create_job(
                format, original_path="", options=options, status="receiving", user_id=user_id
            )
            path, sha256, _size = self._gateway.copy_original(job_id, source, extension)
            await self._gateway.update_job(
                job_id, original_path=str(path), file_sha256=sha256, status="uploaded"
            )
            queued.append({"id": job_id, "filename": name})
        return batch_id, queued

    async def scan_incoming(self, principal: Principal) -> dict:
        files = self._gateway.import_files(self._config.incoming_dir, False)
        _batch, queued = await self._enqueue_batch(
            files, auto_commit=False, group_series=False, user_id=principal.user_id
        )
        return {"queued": queued, "count": len(queued)}

    async def batch(self, principal: Principal, *, path: str | None, recursive: bool,
                    auto_commit: bool, group_series: bool) -> dict:
        root = path or self._config.incoming_dir
        if not self._gateway.is_directory(root):
            raise ImportRequestError(400, f"Not a directory: {root}")
        files = self._gateway.import_files(root, recursive)
        if not files:
            raise ImportRequestError(404, f"No .epub/.pdf files found under {root}.")
        batch_id, queued = await self._enqueue_batch(
            files, auto_commit=auto_commit, group_series=group_series,
            user_id=principal.user_id,
        )
        return {"batch_id": batch_id, "queued": queued, "count": len(queued)}

    async def upload_init(self, filename: str, size: int, principal: Principal) -> dict:
        self._quota.ensure_allowed(principal)
        extension, format = self._format(filename)
        size = int(size or 0)
        if size <= 0:
            raise ImportRequestError(422, "A positive declared file size is required.")
        if size > self._config.max_chunked_bytes:
            raise ImportRequestError(
                413, f"File exceeds the {self._config.max_chunked_upload_mb} MB upload cap."
            )
        job_id = await self._gateway.create_job(
            format, original_path="",
            options={"upload": {"size": size, "ext": extension.lstrip(".")}},
            status="receiving", user_id=principal.user_id,
        )
        path = self._gateway.init_upload(job_id, extension)
        await self._gateway.update_job(job_id, original_path=str(path))
        return {"id": job_id, "offset": 0, "format": format}

    async def upload_status(self, job_id: int, principal: Principal) -> dict:
        job = await self._own_job(job_id, principal)
        upload = (job.get("options") or {}).get("upload") or {}
        extension = upload.get("ext", job["format"])
        return {"id": job_id, "offset": self._gateway.upload_offset(job_id, extension),
                "size": upload.get("size", 0), "complete": job["status"] != "receiving"}

    async def upload_chunk(self, job_id: int, offset_header: str, data: bytes,
                           principal: Principal) -> dict:
        job = await self._own_job(job_id, principal)
        if job["status"] != "receiving":
            raise ImportRequestError(409, "Upload session is not open.")
        upload = (job.get("options") or {}).get("upload") or {}
        extension = upload.get("ext", job["format"])
        declared = int(upload.get("size") or 0)
        try:
            offset = int(offset_header)
        except ValueError:
            raise ImportRequestError(400, "Invalid Upload-Offset header.")
        if offset < 0:
            raise ImportRequestError(400, "Upload-Offset must be non-negative.")
        if not data:
            raise ImportRequestError(400, "Empty chunk.")
        current = self._gateway.upload_offset(job_id, extension)
        if offset + len(data) <= current:
            if not self._gateway.chunk_matches(job_id, extension, offset, data):
                raise ImportRequestError(409, "Chunk conflicts with already-received bytes.",
                                         {"Upload-Offset": str(current)})
            await self._gateway.touch_job(job_id)
            return {"offset": current}
        if offset != current:
            raise ImportRequestError(409, "Stale upload offset; resume from the current cursor.",
                                     {"Upload-Offset": str(current)})
        if declared and offset + len(data) > declared:
            raise ImportRequestError(413, "Chunk would exceed the declared upload size.")
        new_offset = self._gateway.write_chunk(job_id, extension, offset, data)
        await self._gateway.touch_job(job_id)
        return {"offset": new_offset}

    async def upload_complete(self, job_id: int, principal: Principal) -> dict:
        self._quota.ensure_allowed(principal)
        job = await self._own_job(job_id, principal)
        if job["status"] != "receiving":
            return {"id": job_id, "status": job["status"]}
        upload = (job.get("options") or {}).get("upload") or {}
        extension = upload.get("ext", job["format"])
        declared = int(upload.get("size") or 0)
        if declared <= 0:
            raise ImportRequestError(400, "Upload has no declared size; re-initialize the upload.")
        size = self._gateway.upload_offset(job_id, extension)
        if size != declared:
            raise ImportRequestError(
                400, f"Upload incomplete: have {size} bytes, expected {declared}."
            )
        sha256, _size = self._gateway.finalize_upload(job_id, extension)
        await self._gateway.update_job(
            job_id, file_sha256=sha256, status="uploaded", stage=None
        )
        duplicates = await self._gateway.duplicate_imports(sha256, job_id)
        return {"id": job_id, "status": "uploaded", "format": job["format"],
                "duplicate_of": duplicates}

    async def commit_series(self, job_ids: list[int], principal: Principal) -> dict:
        if len(job_ids) < 1:
            raise ImportRequestError(422, "Provide at least one job id.")
        for job_id in job_ids:
            job = await self._own_job(job_id, principal)
            if job["status"] not in ("awaiting_review", "failed"):
                raise ImportRequestError(
                    409, f"Job {job_id} is '{job['status']}', not ready to commit."
                )
        try:
            return await self._gateway.commit_series(job_ids)
        except ValueError as exc:
            raise ImportRequestError(409, str(exc)) from exc

    async def list_jobs(self, principal: Principal) -> list[dict]:
        scope = None if principal.is_admin else principal.user_id
        return [job_view(job) for job in await self._gateway.list_jobs(scope)]

    async def get_job(self, job_id: int, principal: Principal) -> dict:
        return job_view(await self._own_job(job_id, principal))

    async def update_plan(self, job_id: int, plan: dict, principal: Principal) -> dict:
        job = await self._own_job(job_id, principal)
        if job["status"] in ("committing", "committed"):
            raise ImportRequestError(409, "This job has already been committed.")
        segments = plan.get("segments")
        if not isinstance(segments, list) or not segments:
            raise ImportRequestError(422, "Plan must contain a non-empty 'segments' list.")
        block_count = self._gateway.block_count(job_id)
        for segment in segments:
            block_range = segment.get("block_range")
            if not (isinstance(block_range, list) and len(block_range) == 2
                    and isinstance(block_range[0], int) and isinstance(block_range[1], int)
                    and 0 <= block_range[0] <= block_range[1]
                    and (block_count is None or block_range[1] < block_count)):
                raise ImportRequestError(
                    422, f"Segment '{segment.get('id')}' has an invalid block_range."
                )
        plan.setdefault("version", 1)
        await self._gateway.update_job(job_id, plan=plan)
        return {"status": "success"}

    async def commit(self, job_id: int, principal: Principal, *, mode: str,
                     novel_id: int | None, source_id: int | None, offset: float,
                     is_raw: bool | None) -> dict:
        job = await self._own_job(job_id, principal)
        if mode == "append" and novel_id:
            await self._catalog.require_editable(novel_id, principal)
        elif mode == "replace" and source_id:
            target_novel = await self._gateway.source_novel_id(source_id)
            if target_novel:
                await self._catalog.require_editable(target_novel, principal)
        if job["status"] not in ("awaiting_review", "failed"):
            raise ImportRequestError(409, f"Job is '{job['status']}', not ready to commit.")
        if not (job.get("plan") and job["plan"].get("segments")):
            raise ImportRequestError(409, "Job has no plan to commit; re-parse it first.")
        if mode == "append":
            if not novel_id:
                raise ImportRequestError(422, "Append mode requires a novel_id.")
            target: Any = {"novel_id": novel_id, "offset": offset}
        elif mode == "replace":
            if not source_id:
                raise ImportRequestError(422, "Replace mode requires a source_id.")
            target = {"source_id": source_id, "offset": offset}
        else:
            target = "new"
        options = {**(job.get("options") or {}), "target": target}
        if is_raw is not None:
            options["is_raw"] = is_raw
        await self._gateway.update_job(
            job_id, options=options, status="committing", error=None
        )
        return {"status": "committing"}

    async def confirm_ocr(self, job_id: int, gemini_first: bool,
                          principal: Principal) -> dict:
        self._quota.ensure_allowed(principal)
        job = await self._own_job(job_id, principal)
        if job["status"] not in ("awaiting_ocr_confirm", "ocr_paused"):
            raise ImportRequestError(
                409, f"Job is '{job['status']}', not awaiting OCR confirmation."
            )
        pages = int(((job.get("cost_estimate") or {}).get("pages"))
                    or ((job.get("progress") or {}).get("total")) or 0)
        if pages > 0:
            await self._quota.reserve_ocr(principal, pages)
        options = {**(job.get("options") or {}), "gemini_first": gemini_first}
        await self._gateway.update_job(
            job_id, options=options, status="ocr_pending", stage="OCR queued", error=None
        )
        return {"status": "ocr_pending"}

    async def cancel(self, job_id: int, principal: Principal) -> dict:
        await self._own_job(job_id, principal)
        await self._gateway.update_job(job_id, status="canceled", stage="canceled")
        return {"status": "canceled"}

    async def delete(self, job_id: int, principal: Principal) -> dict:
        await self._own_job(job_id, principal)
        await self._gateway.delete_job(job_id)
        self._gateway.cleanup_job(job_id)
        return {"status": "success"}
