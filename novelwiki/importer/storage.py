"""On-disk layout + IO for the import pipeline.

Heavy artifacts live on disk, pointers in the DB. Layout under the configured dirs::

    IMPORT_DIR/<job_id>/original.<ext>     the uploaded blob (kept so we can re-segment)
    IMPORT_DIR/<job_id>/blocks.json        the serialized IR (Document) the job produced
    ASSET_DIR/_jobs/<job_id>/<sha>.<ext>   staged images, servable for preview thumbnails
    ASSET_DIR/<novel_id>/<sha>.<ext>       committed images, referenced by the reader

Images are content-addressed by sha256 so the same illustration shared across chapters is
stored once. Staged assets sit *under* ASSET_DIR (which is mounted at /assets) so the plan
editor can show thumbnails before commit; ``commit_asset`` promotes them to the novel dir.
"""
from __future__ import annotations

import hashlib
import logging
import shutil
from pathlib import Path

from novelwiki.config.settings import settings
from novelwiki.importer.ir import Document

logger = logging.getLogger(__name__)

# Minimal mime ↔ extension maps for the image types EPUB/PDF actually carry.
_MIME_EXT = {
    "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/gif": "gif",
    "image/webp": "webp", "image/svg+xml": "svg", "image/bmp": "bmp", "image/tiff": "tiff",
}
_EXT_MIME = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
    "webp": "image/webp", "svg": "image/svg+xml", "bmp": "image/bmp", "tiff": "image/tiff",
}


def ext_from_mime(mime: str | None) -> str:
    return _MIME_EXT.get((mime or "").lower().split(";")[0].strip(), "bin")


def mime_from_ext(ext: str) -> str:
    return _EXT_MIME.get((ext or "").lower().lstrip("."), "application/octet-stream")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── Directory roots ─────────────────────────────────────────────────────────

def _import_root() -> Path:
    return Path(settings.IMPORT_DIR)


def _asset_root() -> Path:
    return Path(settings.ASSET_DIR)


def ensure_dirs() -> None:
    """Create the import/asset/incoming roots (idempotent). Called at worker startup."""
    for p in (_import_root(), _asset_root(), Path(settings.IMPORT_INCOMING_DIR), _asset_root() / "_jobs"):
        p.mkdir(parents=True, exist_ok=True)


# ── Job scratch ─────────────────────────────────────────────────────────────

def job_dir(job_id: int) -> Path:
    d = _import_root() / str(job_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def original_path(job_id: int, ext: str) -> Path:
    return job_dir(job_id) / f"original.{ext.lstrip('.')}"


def save_original(job_id: int, data: bytes, ext: str) -> Path:
    p = original_path(job_id, ext)
    p.write_bytes(data)
    return p


# ── Resumable chunked upload (tus-style) ────────────────────────────────────
# Big files over the Cloudflare tunnel can't ride a single multipart POST, so the client
# uploads them in chunks: init creates an empty blob, each chunk is written at its byte
# offset, and the on-disk file size IS the resume cursor (no separate bookkeeping needed).

def init_upload(job_id: int, ext: str) -> Path:
    """Create the (empty) target blob for a chunked upload so chunks can seek into it."""
    p = original_path(job_id, ext)
    if not p.exists():
        p.write_bytes(b"")
    return p


def upload_offset(job_id: int, ext: str) -> int:
    """Current received size = the resume cursor. 0 if nothing has landed yet."""
    p = original_path(job_id, ext)
    return p.stat().st_size if p.exists() else 0


def write_chunk(job_id: int, ext: str, offset: int, data: bytes) -> int:
    """Write a chunk at ``offset`` and return the new received size. Idempotent on retried
    chunks (a client may resend the last chunk); seeking past the end zero-fills any gap,
    but the client is expected to send contiguous offsets."""
    p = original_path(job_id, ext)
    with open(p, "r+b") as f:
        f.seek(offset)
        f.write(data)
    return p.stat().st_size


def finalize_upload(job_id: int, ext: str) -> tuple[str, int]:
    """Hash the fully-assembled blob and return (sha256, size)."""
    p = original_path(job_id, ext)
    return sha256_bytes(p.read_bytes()), p.stat().st_size


def blocks_path(job_id: int) -> Path:
    return job_dir(job_id) / "blocks.json"


def save_blocks(job_id: int, document: Document) -> Path:
    p = blocks_path(job_id)
    p.write_text(document.to_json(), encoding="utf-8")
    return p


def load_blocks(job_id: int) -> Document:
    return Document.from_json(blocks_path(job_id).read_text(encoding="utf-8"))


def has_blocks(job_id: int) -> bool:
    return blocks_path(job_id).exists()


# ── Staged (pre-commit) assets ──────────────────────────────────────────────

def _staged_dir(job_id: int) -> Path:
    d = _asset_root() / "_jobs" / str(job_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def stage_asset(job_id: int, data: bytes, mime: str | None) -> tuple[str, str]:
    """Write an extracted image to the job's staging dir, content-addressed. Returns
    (sha, ext). Idempotent: re-staging identical bytes is a no-op (dedup by sha)."""
    sha = sha256_bytes(data)
    ext = ext_from_mime(mime)
    dest = _staged_dir(job_id) / f"{sha}.{ext}"
    if not dest.exists():
        dest.write_bytes(data)
    return sha, ext


def staged_asset_url(job_id: int, sha: str, ext: str) -> str:
    return f"/assets/_jobs/{job_id}/{sha}.{ext}"


def staged_asset_path(job_id: int, sha: str, ext: str) -> Path:
    return _staged_dir(job_id) / f"{sha}.{ext}"


# ── Committed assets ────────────────────────────────────────────────────────

def asset_rel(novel_id: int, sha: str, ext: str) -> str:
    """The path stored in assets.path, relative to ASSET_DIR (so it can move hosts)."""
    return f"{novel_id}/{sha}.{ext}"


def asset_url(novel_id: int, sha: str, ext: str) -> str:
    return f"/assets/{asset_rel(novel_id, sha, ext)}"


async def commit_asset(
    conn, novel_id: int, job_id: int, sha: str, ext: str,
    mime: str | None, kind: str, width: int | None = None, height: int | None = None,
) -> str:
    """Promote a staged image into the novel's asset dir and record it (dedup by sha).
    Returns the relative path. Safe to call repeatedly for the same (novel, sha)."""
    rel = asset_rel(novel_id, sha, ext)
    dest = _asset_root() / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = staged_asset_path(job_id, sha, ext)
    if not dest.exists():
        if src.exists():
            shutil.copyfile(src, dest)
        else:
            logger.warning(f"commit_asset: staged source missing for sha {sha[:12]} (job {job_id}).")
    await conn.execute(
        """
        INSERT INTO assets (novel_id, sha256, path, mime, kind, width, height)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (novel_id, sha256) DO NOTHING;
        """,
        novel_id, sha, rel, mime, kind, width, height,
    )
    return rel


# ── Cleanup ─────────────────────────────────────────────────────────────────

def cleanup_job(job_id: int) -> None:
    """Remove a job's scratch dir and its staged assets (called on cancel/delete)."""
    shutil.rmtree(job_dir(job_id), ignore_errors=True)
    shutil.rmtree(_staged_dir(job_id), ignore_errors=True)


def cleanup_novel_assets(novel_id: int) -> None:
    """Remove a novel's committed asset dir. The assets DB rows are FK-cascaded when the
    novel is deleted, but the files on disk are not — this frees them."""
    shutil.rmtree(_asset_root() / str(novel_id), ignore_errors=True)
