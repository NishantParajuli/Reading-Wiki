"""Application commands used by the Acquisition CLI transport."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class AcquisitionCommandGateway(Protocol):
    async def safe_url(self, url: str) -> str: ...
    async def create_novel(self, **fields: Any) -> tuple[int, int]: ...
    async def scrape_source(self, source_id: int, **fields: Any) -> int: ...
    async def scrape_novel(self, novel_id: int, **fields: Any) -> int: ...
    def ensure_storage(self) -> None: ...
    async def create_job(self, fmt: str, path: str, options: dict, status: str) -> int: ...
    def parse(self, fmt: str, path: str, job_id: int): ...
    def clean(self, document: Any) -> None: ...
    def save_blocks(self, job_id: int, document: Any) -> None: ...
    def plan(self, document: Any) -> dict: ...
    def quality(self, document: Any, plan: dict) -> dict: ...
    async def update_job(self, job_id: int, **fields: Any) -> None: ...
    async def get_job(self, job_id: int) -> dict: ...
    async def commit_job(self, job: dict) -> dict: ...
    async def commit_series(self, job_ids: list[int]) -> dict: ...
    async def build_codex(self, novel_id: int, start: float, end: float) -> None: ...


class ScannedPdfError(RuntimeError):
    pass


class AcquisitionCommands:
    def __init__(self, gateway: AcquisitionCommandGateway):
        self._gateway = gateway

    async def add_novel(self, **fields: Any) -> tuple[int, int]:
        fields["start_url"] = await self._gateway.safe_url(fields["start_url"])
        return await self._gateway.create_novel(**fields)

    async def scrape(self, novel_id: int, source_id: int | None, force: bool,
                     max_chapters: int | None) -> int:
        if source_id is not None:
            return await self._gateway.scrape_source(
                source_id, force=force, max_chapters=max_chapters,
                expected_novel_id=novel_id,
            )
        return await self._gateway.scrape_novel(
            novel_id, force=force, max_chapters=max_chapters
        )

    async def parse_into_job(self, path: str, fmt: str,
                             options: dict | None = None) -> int:
        gateway = self._gateway
        gateway.ensure_storage()
        absolute = str(Path(path).resolve())
        job_id = await gateway.create_job(fmt, absolute, options or {}, "receiving")
        document = gateway.parse(fmt, path, job_id)
        if document.meta.get("scanned"):
            raise ScannedPdfError(
                f"{Path(path).name} is a scanned PDF — import it from the web UI (OCR)."
            )
        gateway.clean(document)
        gateway.save_blocks(job_id, document)
        plan = gateway.plan(document)
        await gateway.update_job(
            job_id, plan=plan, status="awaiting_review",
            detected_meta={
                "title": document.meta.get("title"),
                "series": document.meta.get("series"),
                "series_index": document.meta.get("series_index"),
            },
            stats={"quality": gateway.quality(document, plan)},
        )
        return job_id

    async def import_file(self, path: str, fmt: str, novel_id: int | None,
                          offset: float, codex: bool) -> dict:
        target: object = {"novel_id": novel_id, "offset": offset} if novel_id else "new"
        job_id = await self.parse_into_job(path, fmt, {"target": target})
        job = await self._gateway.get_job(job_id)
        result = await self._gateway.commit_job(job)
        await self._gateway.update_job(
            job_id, status="committed", novel_id=result["novel_id"],
            source_id=result.get("source_id"),
        )
        stats = result["stats"]
        if codex:
            await self._gateway.build_codex(
                result["novel_id"], stats["from_chapter"], stats["to_chapter"]
            )
        return {**result, "job_id": job_id, "segments": len(job["plan"]["segments"]),
                "included": sum(bool(item.get("include")) for item in job["plan"]["segments"])}

    async def import_batch(self, paths: list[str], group_series: bool,
                           codex: bool) -> tuple[list[dict], list[tuple[str, str]]]:
        parsed: list[tuple[int, str | None]] = []
        errors: list[tuple[str, str]] = []
        for path in paths:
            fmt = "epub" if path.lower().endswith(".epub") else "pdf"
            try:
                job_id = await self.parse_into_job(path, fmt)
                job = await self._gateway.get_job(job_id)
                parsed.append((job_id, (job.get("detected_meta") or {}).get("series")))
            except Exception as exc:
                errors.append((path, str(exc)))
        novels: list[dict] = []
        if group_series:
            groups: dict[str, list[int]] = {}
            for job_id, name in parsed:
                groups.setdefault(name or f"__single_{job_id}", []).append(job_id)
            for key, ids in groups.items():
                if key.startswith("__single_") or len(ids) == 1:
                    novels.append(await self._gateway.commit_job(await self._gateway.get_job(ids[0])))
                else:
                    result = await self._gateway.commit_series(ids)
                    result["series_name"] = key
                    novels.append(result)
        else:
            for job_id, _name in parsed:
                novels.append(await self._gateway.commit_job(await self._gateway.get_job(job_id)))
        if codex:
            for result in novels:
                stats = result.get("stats", {})
                if stats.get("from_chapter") is not None:
                    await self._gateway.build_codex(
                        result["novel_id"], stats["from_chapter"], stats["to_chapter"]
                    )
        return novels, errors

    async def import_series(self, paths: list[str], codex: bool) -> dict:
        ids = []
        for path in paths:
            fmt = "epub" if path.lower().endswith(".epub") else "pdf"
            ids.append(await self.parse_into_job(path, fmt))
        result = await self._gateway.commit_series(ids)
        stats = result["stats"]
        if codex:
            await self._gateway.build_codex(
                result["novel_id"], stats["from_chapter"], stats["to_chapter"]
            )
        return result
