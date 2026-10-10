"""Background worker: claims jobs from Postgres (SKIP LOCKED) and runs FFmpeg.

    python -m media_service.worker

Separate process from the API — FFmpeg/FFprobe always run here, in isolated
subprocesses with timeouts, never in the request path.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import time
from pathlib import Path

from . import db, media, storage
from .config import (
    DATABASE_URL,
    JOB_MAX_ATTEMPTS,
    MAX_VIDEO_SECONDS,
    PROXY_DURATION_TOLERANCE_S,
    WORKER_POLL_SECONDS,
    WORKER_REAP_SECONDS,
    WORKER_STALE_JOB_SECONDS,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("media.worker")


class Skip(Exception):
    """Job skipped (e.g. asset was deleted mid-flight) — count as done, not failed."""


# ------------------------------------------------------------------ handlers

async def _download(key: str, dst: Path) -> None:
    data = await asyncio.to_thread(storage.download, key)
    dst.write_bytes(data)


async def _upload(local: Path, key: str, content_type: str) -> None:
    await asyncio.to_thread(storage.upload_file, str(local), key, content_type)


def _ffmpeg_in_thread(args: list[str]) -> None:
    media.run(args)


async def handle_probe(job: dict, workdir: Path) -> dict:
    src = workdir / "source"
    await _download(job["storage_key"], src)
    info = await asyncio.to_thread(media.probe, str(src))
    if not info["has_video"]:
        raise media.MediaError("That file has no video stream.")
    if info["duration"] and info["duration"] > MAX_VIDEO_SECONDS + 1:
        raise media.MediaError(f"That video is longer than {MAX_VIDEO_SECONDS // 60} minutes.")
    return {
        "asset_values": {
            "duration_ms": round(info["duration"] * 1000),
            "metadata": {k: v for k, v in info.items() if k != "duration"}
                       | {"duration_s": round(info["duration"], 3)},
        },
    }


async def handle_thumbnail(job: dict, workdir: Path) -> dict:
    src = workdir / "source"
    await _download(job["storage_key"], src)
    info = await asyncio.to_thread(media.probe, str(src))
    offset = min(1.0, max(0.0, info["duration"] * 0.1)) if info["duration"] else 1.0
    dst = workdir / "thumb.jpg"
    await asyncio.to_thread(
        lambda: media.run(media.thumbnail_args(str(src), str(dst), offset))
    )
    if job.get("deleted_at"):
        raise Skip("asset deleted")
    thumb_key, _ = _derivatives(job["storage_key"])
    await _upload(dst, thumb_key, "image/jpeg")
    return {}


async def handle_proxy(job: dict, workdir: Path) -> dict:
    src = workdir / "source"
    await _download(job["storage_key"], src)
    info = await asyncio.to_thread(media.probe, str(src))
    dst = workdir / "proxy.mp4"
    await asyncio.to_thread(lambda: media.run(media.proxy_args(str(src), str(dst))))
    out = await asyncio.to_thread(media.probe, str(dst))
    if abs(out["duration"] - info["duration"]) > PROXY_DURATION_TOLERANCE_S:
        raise media.MediaError(
            f"Proxy duration {out['duration']:.2f}s doesn't match source {info['duration']:.2f}s."
        )
    if job.get("deleted_at"):
        raise Skip("asset deleted")
    _, proxy_key = _derivatives(job["storage_key"])
    await _upload(dst, proxy_key, "video/mp4")
    return {}


def _derivatives(storage_key: str) -> tuple[str, str]:
    prefix = storage_key.rsplit("/", 1)[0]
    return f"{prefix}/thumb.jpg", f"{prefix}/proxy.mp4"


async def handle_cleanup(job: dict, workdir: Path) -> dict:
    prefix = job["storage_key"].rsplit("/", 1)[0]
    keys = [f"{prefix}/source{ext}" for ext in (".mp4", ".mov", ".webm", ".mkv")]
    keys += [f"{prefix}/thumb.jpg", f"{prefix}/proxy.mp4"]
    # Remove only objects that exist (list the folder once).
    folder = prefix
    try:
        entries = await asyncio.to_thread(
            lambda: storage.admin().storage.from_(storage.MEDIA_BUCKET).list(folder) or []
        )
        existing = [f"{folder}/{e.name}" for e in entries if getattr(e, "name", None)]
    except Exception as e:
        log.warning("cleanup list failed for %s: %s", prefix, e)
        existing = keys
    await asyncio.to_thread(storage.remove, existing)
    log.info("cleanup: removed %d object(s) for asset %s", len(existing), job["asset_id"])
    return {}


HANDLERS = {
    "probe": handle_probe,
    "thumbnail": handle_thumbnail,
    "proxy": handle_proxy,
    "cleanup": handle_cleanup,
}

# The job row carries asset columns joined in (see claim_one).
JOB_SELECT = """
select j.*, a.storage_key, a.deleted_at
from jobs j join assets a on a.id = j.asset_id
where j.id = $1
"""


# ------------------------------------------------------------------ loop

async def claim_one(pool) -> dict | None:
    job = await db.claim_job(pool)
    if job is None:
        return None
    row = await pool.fetchrow(JOB_SELECT, job["id"])
    return dict(row) if row else job


async def process_one(pool) -> bool:
    """Claim and run one job. Returns True when a job was claimed."""
    job = await claim_one(pool)
    if job is None:
        return False
    kind, asset_id = job["kind"], job["asset_id"]
    log.info("job %s kind=%s asset=%s attempt=%s", job["id"], kind, asset_id, job["attempts"])

    if kind != "cleanup" and job.get("deleted_at"):
        await db.finish_job(pool, job, ok=True, error=None)
        log.info("job %s skipped: asset soft-deleted", job["id"])
        return True

    handler = HANDLERS.get(kind)
    started = time.monotonic()
    try:
        if handler is None:
            raise media.MediaError(f"Unknown job kind {kind!r}.")
        with tempfile.TemporaryDirectory(prefix=f"media-{kind}-") as td:
            result = await handler(job, Path(td))
        await db.finish_job(pool, job, ok=True, asset_values=result.get("asset_values"))
        log.info("job %s done in %.1fs", job["id"], time.monotonic() - started)
    except Skip as e:
        await db.finish_job(pool, job, ok=True)
        log.info("job %s skipped: %s", job["id"], e)
    except media.MediaError as e:
        await db.finish_job(pool, job, ok=False, error=str(e))
        log.warning("job %s failed (attempt %s/%s): %s",
                    job["id"], job["attempts"], JOB_MAX_ATTEMPTS, e)
    except Exception as e:
        await db.finish_job(pool, job, ok=False, error=f"{type(e).__name__}: {e}")
        log.exception("job %s crashed", job["id"])
    return True


async def main() -> None:
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL must be set in .env (Supabase direct/session pooler).")
    pool = await db.connect()
    log.info("worker ready (poll every %.2fs, max %s attempts)", WORKER_POLL_SECONDS, JOB_MAX_ATTEMPTS)
    last_reap = float("-inf")  # reap once immediately at startup
    try:
        while True:
            try:
                if time.monotonic() - last_reap >= WORKER_REAP_SECONDS:
                    last_reap = time.monotonic()
                    for j in await db.requeue_stale_jobs(pool, WORKER_STALE_JOB_SECONDS):
                        log.warning("requeued stale job %s kind=%s asset=%s (attempt %s)",
                                    j["id"], j["kind"], j["asset_id"], j["attempts"])
                worked = await process_one(pool)
            except Exception:
                log.exception("worker loop error")
                worked = False
            if not worked:
                await asyncio.sleep(WORKER_POLL_SECONDS)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
