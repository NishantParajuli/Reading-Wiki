from __future__ import annotations

import os


class ImportRuntimeGateway:
    """Adapter over the existing durable importer and filesystem implementation."""

    def __init__(self, pool):
        self._pool = pool

    async def create_job(self, format: str, **fields) -> int:
        from novelwiki.modules.acquisition.adapters.inbound import worker as jobs
        return await jobs.create_job(format, **fields)

    async def get_job(self, job_id: int) -> dict | None:
        from novelwiki.modules.acquisition.adapters.inbound import worker as jobs
        return await jobs.get_job(job_id)

    async def list_jobs(self, user_id: int | None) -> list[dict]:
        from novelwiki.modules.acquisition.adapters.inbound import worker as jobs
        return await jobs.list_jobs(user_id=user_id)

    async def update_job(self, job_id: int, **fields) -> None:
        from novelwiki.modules.acquisition.adapters.inbound import worker as jobs
        await jobs.update_job(job_id, **fields)

    async def delete_job(self, job_id: int) -> None:
        async with self._pool.acquire() as connection:
            await connection.execute("DELETE FROM import_jobs WHERE id = $1;", job_id)

    async def duplicate_imports(self, sha256: str, job_id: int) -> list[dict]:
        from novelwiki.modules.acquisition.adapters.inbound import worker as jobs
        return await jobs.imports_with_hash(sha256, exclude_job_id=job_id)

    async def source_novel_id(self, source_id: int) -> int | None:
        async with self._pool.acquire() as connection:
            value = await connection.fetchval(
                "SELECT novel_id FROM sources WHERE id = $1;", source_id,
            )
        return int(value) if value is not None else None

    async def save_upload(self, job_id: int, upload, extension: str, max_bytes: int):
        from novelwiki.modules.acquisition.adapters.outbound.importer import storage
        return await storage.save_upload_file_limited(
            job_id, upload, extension, max_bytes,
        )

    def cleanup_job(self, job_id: int) -> None:
        from novelwiki.modules.acquisition.adapters.outbound.importer import storage
        storage.cleanup_job(job_id)

    def init_upload(self, job_id: int, extension: str):
        from novelwiki.modules.acquisition.adapters.outbound.importer import storage
        return storage.init_upload(job_id, extension)

    def upload_offset(self, job_id: int, extension: str) -> int:
        from novelwiki.modules.acquisition.adapters.outbound.importer import storage
        return storage.upload_offset(job_id, extension)

    def chunk_matches(
        self, job_id: int, extension: str, offset: int, data: bytes
    ) -> bool:
        from novelwiki.modules.acquisition.adapters.outbound.importer import storage
        return storage.chunk_matches(job_id, extension, offset, data)

    def write_chunk(
        self, job_id: int, extension: str, offset: int, data: bytes
    ) -> int:
        from novelwiki.modules.acquisition.adapters.outbound.importer import storage
        return storage.write_chunk(job_id, extension, offset, data)

    def finalize_upload(self, job_id: int, extension: str) -> tuple[str, int]:
        from novelwiki.modules.acquisition.adapters.outbound.importer import storage
        return storage.finalize_upload(job_id, extension)

    async def touch_job(self, job_id: int) -> None:
        from novelwiki.modules.acquisition.adapters.inbound import worker as jobs
        await jobs.touch_job(job_id)

    def import_files(self, root: str, recursive: bool) -> list[tuple[str, str]]:
        files: list[tuple[str, str]] = []
        formats = {".epub", ".pdf"}
        if recursive:
            for directory, _subdirs, names in os.walk(root):
                for name in sorted(names):
                    if os.path.splitext(name)[1].lower() in formats:
                        files.append((os.path.join(directory, name), name))
        else:
            try:
                names = sorted(os.listdir(root))
            except FileNotFoundError:
                return []
            for name in names:
                source = os.path.join(root, name)
                if os.path.isfile(source) and os.path.splitext(name)[1].lower() in formats:
                    files.append((source, name))
        return files

    def ensure_dirs(self) -> None:
        from novelwiki.modules.acquisition.adapters.outbound.importer import storage
        storage.ensure_dirs()

    def copy_original(self, job_id: int, source: str, extension: str):
        from novelwiki.modules.acquisition.adapters.outbound.importer import storage
        return storage.save_original_from_path(job_id, source, extension)

    def is_directory(self, root: str) -> bool:
        return os.path.isdir(root)

    def block_count(self, job_id: int) -> int | None:
        from novelwiki.modules.acquisition.adapters.outbound.importer import storage
        try:
            return len(storage.load_blocks(job_id).blocks)
        except Exception:
            return None

    async def commit_series(self, job_ids: list[int]) -> dict:
        from novelwiki.modules.acquisition.adapters.outbound.importer import commit
        return await commit.commit_series(job_ids)
