"""Pure helpers shared by the API routes and the worker (easy to unit-test)."""

from __future__ import annotations

import uuid
from pathlib import Path

from .config import (
    ASSET_MAX_COUNT,
    ASSET_MAX_TOTAL_BYTES,
    JOB_MAX_ATTEMPTS,
    JOB_RETRY_BASE_SECONDS,
    MAX_UPLOAD_BYTES,
    MAX_VIDEO_SECONDS,
)

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".webm", ".mkv"}


class ValidationError(ValueError):
    """Maps to HTTP 422/400 in the routes."""


def normalize_filename(original_filename: str) -> str:
    """Keep a safe display name; the storage key never uses it."""
    name = (original_filename or "").strip()
    if any(ord(c) < 32 for c in name):
        raise ValidationError("That file name isn't allowed. Rename it and try again.")
    # Never trust a client-sent path — keep the final segment only.
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    if not name or name.startswith(".") or len(name) > 200:
        raise ValidationError("That file name isn't allowed. Rename it and try again.")
    if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise ValidationError("Use MP4, MOV, WebM or MKV.")
    return name


def validate_init(original_filename: str, size_bytes, duration_ms) -> dict:
    """Checks run BEFORE a signed upload URL is issued."""
    name = normalize_filename(original_filename)
    try:
        size = int(size_bytes)
        duration = int(duration_ms) if duration_ms is not None else None
    except (TypeError, ValueError):
        raise ValidationError("size_bytes and duration_ms must be numbers.")
    if size <= 0:
        raise ValidationError("That file is empty.")
    if size > MAX_UPLOAD_BYTES:
        raise ValidationError(f"That file is over {MAX_UPLOAD_BYTES // 1_000_000} MB.")
    if duration is not None:
        if duration <= 0:
            raise ValidationError("That video has no duration.")
        if duration > (MAX_VIDEO_SECONDS + 1) * 1000:
            raise ValidationError(f"That video is longer than {MAX_VIDEO_SECONDS // 60} minutes.")
    return {"original_filename": name, "size_bytes": size, "duration_ms": duration}


def check_quota(count: int, total_bytes: int, incoming_bytes: int) -> None:
    """Count / total-bytes quota for one owner (deleted assets excluded by the query)."""
    if count >= ASSET_MAX_COUNT:
        raise ValidationError(
            f"Your library is full ({ASSET_MAX_COUNT} videos). Remove some and try again."
        )
    if total_bytes + incoming_bytes > ASSET_MAX_TOTAL_BYTES:
        gb = ASSET_MAX_TOTAL_BYTES / 1_000_000_000
        raise ValidationError(f"That would exceed your {gb:g} GB library storage limit.")


def build_storage_key(owner_id: str, asset_id: str, original_filename: str) -> str:
    """Opaque key: {user_id}/{asset_id}/source.ext — never the original name."""
    ext = Path(original_filename).suffix.lower()
    return f"{owner_id}/{asset_id}/source{ext}"


def new_asset_id() -> str:
    return str(uuid.uuid4())


def backoff_seconds(attempts: int) -> int:
    """Exponential backoff for a retried job: 30s, 60s, 120s, ..."""
    attempts = max(1, attempts)
    return JOB_RETRY_BASE_SECONDS * (2 ** min(attempts - 1, 10))


def attempts_exhausted(attempts: int) -> bool:
    return attempts >= JOB_MAX_ATTEMPTS


def asset_rollup(metadata_status: str, thumbnail_status: str, proxy_status: str,
                 failed_permanently: bool) -> str:
    """New asset status after a job finished (PROCESSING is set at claim time)."""
    statuses = (metadata_status, thumbnail_status, proxy_status)
    if "FAILED" in statuses:
        # A task marked FAILED only stays failed permanently once retries are exhausted;
        # the worker passes failed_permanently=True in that case.
        return "FAILED" if failed_permanently else "PROCESSING"
    if all(s == "READY" for s in statuses):
        return "READY"
    return "PROCESSING"
