"""On-disk layout + IO for the import pipeline.

Heavy artifacts live on disk, pointers in the DB. Layout under the configured dirs::

    IMPORT_DIR/<job_id>/original.<ext>     the uploaded blob (kept so we can re-segment)
    IMPORT_DIR/<job_id>/blocks.json        the serialized IR (Document) the job produced
    ASSET_DIR/_jobs/<job_id>/<sha>.<ext>   staged images, served by authenticated routes
    ASSET_DIR/<novel_id>/<sha>.<ext>       committed images, referenced by the reader

Images are content-addressed by sha256 so the same illustration shared across chapters is
stored once. Staged assets sit *under* ASSET_DIR and are served through access-controlled
API routes; ``commit_asset`` promotes them to the novel dir.
"""
from __future__ import annotations

import hashlib
import io
import logging
import shutil
from pathlib import Path

from novelwiki.config.settings import settings
from novelwiki.importer.ir import Document

logger = logging.getLogger(__name__)

# Minimal mime ↔ extension maps for the image types EPUB/PDF actually carry.
_MIME_EXT = {
    "image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png", "image/gif": "gif",
    "image/webp": "webp", "image/bmp": "bmp", "image/tiff": "tiff",
}
_EXT_MIME = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif",
    "webp": "image/webp", "bmp": "image/bmp", "tiff": "image/tiff",
}
ALLOWED_ASSET_EXTS = frozenset(_EXT_MIME.keys())


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
    _validate_raster_asset(data, mime)
    sha = sha256_bytes(data)
    ext = ext_from_mime(mime)
    dest = _staged_dir(job_id) / f"{sha}.{ext}"
    if not dest.exists():
        dest.write_bytes(data)
    return sha, ext


def staged_asset_url(job_id: int, sha: str, ext: str) -> str:
    return f"/api/assets/import-jobs/{job_id}/{sha}.{ext}"


def staged_asset_path(job_id: int, sha: str, ext: str) -> Path:
    return _staged_dir(job_id) / f"{sha}.{ext}"


def staged_asset_file_path(job_id: int, filename: str) -> Path:
    return _staged_dir(job_id) / filename


# ── Committed assets ────────────────────────────────────────────────────────

def asset_rel(novel_id: int, sha: str, ext: str) -> str:
    """The path stored in assets.path, relative to ASSET_DIR (so it can move hosts)."""
    return f"{novel_id}/{sha}.{ext}"


def asset_url(novel_id: int, sha: str, ext: str) -> str:
    return f"/api/assets/novels/{novel_id}/{sha}.{ext}"


def asset_file_path(novel_id: int, filename: str) -> Path:
    return _asset_root() / str(novel_id) / filename


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


# ── User avatars (multi-user, Phase 3) ───────────────────────────────────────
# Avatars live under ASSET_DIR/_users/<id>/ and are intentionally public via a
# narrowed /assets/_users mount.
# Content-addressed (truncated sha) so re-uploading the same image is a no-op and the
# URL changes when the image does (cache-busting). The DB stores the ASSET_DIR-relative
# path in users.avatar_path; the URL is "/assets/" + that path.

_AVATAR_EXT = {"jpg", "jpeg", "png", "webp", "gif"}


def _user_dir(user_id: int) -> Path:
    d = _asset_root() / "_users" / str(user_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


def user_avatar_rel(user_id: int, name: str) -> str:
    return f"_users/{user_id}/{name}"


def save_user_avatar(user_id: int, data: bytes, ext: str) -> str:
    """Write an avatar image and return its path relative to ASSET_DIR. Older avatars for
    the user are left on disk (cheap); the DB row points at the latest filename."""
    ext = (ext or "png").lower().lstrip(".")
    if ext == "jpeg":
        ext = "jpg"
    if ext not in _AVATAR_EXT:
        ext = "png"
    name = f"{sha256_bytes(data)[:16]}.{ext}"
    (_user_dir(user_id) / name).write_bytes(data)
    return user_avatar_rel(user_id, name)


def _validate_raster_asset(data: bytes, mime: str | None) -> None:
    normalized = (mime or "").lower().split(";", 1)[0].strip()
    if normalized == "image/svg+xml":
        raise ValueError("SVG assets are not supported.")
    ext = ext_from_mime(normalized)
    if ext not in ALLOWED_ASSET_EXTS:
        raise ValueError(f"Unsupported image MIME type: {mime or 'unknown'}.")
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
    except Exception as exc:
        raise ValueError("Image asset could not be decoded safely.") from exc


# ── Cleanup ─────────────────────────────────────────────────────────────────

def cleanup_job(job_id: int) -> None:
    """Remove a job's scratch dir and its staged assets (called on cancel/delete)."""
    shutil.rmtree(job_dir(job_id), ignore_errors=True)
    shutil.rmtree(_staged_dir(job_id), ignore_errors=True)


def cleanup_novel_assets(novel_id: int) -> None:
    """Remove a novel's committed asset dir. The assets DB rows are FK-cascaded when the
    novel is deleted, but the files on disk are not — this frees them."""
    shutil.rmtree(_asset_root() / str(novel_id), ignore_errors=True)
