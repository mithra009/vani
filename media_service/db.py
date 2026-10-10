"""asyncpg access for assets + the jobs queue (SELECT ... FOR UPDATE SKIP LOCKED)."""

from __future__ import annotations
from datetime import timedelta

import json
import logging
from typing import Any

import asyncpg

from .config import CLEANUP_GRACE_SECONDS, DATABASE_URL, JOB_MAX_ATTEMPTS, JOB_RETRY_BASE_SECONDS
from .validators import asset_rollup, attempts_exhausted, backoff_seconds

log = logging.getLogger("media.db")

TASK_COLUMN = {"probe": "metadata_status", "thumbnail": "thumbnail_status", "proxy": "proxy_status"}


def check_connection_string(url: str) -> None:
    """SKIP LOCKED is unreliable through the transaction pooler (port 6543)."""
    if ":6543/" in url:
        raise RuntimeError(
            "DATABASE_URL points at the transaction pooler (:6543). Use the direct "
            "connection (:5432) or the session pooler so SELECT ... FOR UPDATE SKIP LOCKED works."
        )


async def connect(url: str | None = None) -> asyncpg.Pool:
    url = url or DATABASE_URL
    if not url:
        raise RuntimeError("DATABASE_URL must be set in .env (Supabase direct/session pooler).")
    check_connection_string(url)
    return await asyncpg.create_pool(url, min_size=1, max_size=5)


def _row(r: asyncpg.Record | None) -> dict | None:
    return dict(r) if r is not None else None


# ------------------------------------------------------------------ API side

async def quota(pool: asyncpg.Pool, owner_id: str) -> tuple[int, int]:
    r = await pool.fetchrow(
        "select count(*)::int as count, coalesce(sum(size_bytes), 0)::bigint as total "
        "from assets where owner_id = $1 and deleted_at is null",
        owner_id,
    )
    return (r["count"], int(r["total"]))


async def create_asset(pool: asyncpg.Pool, owner_id: str, *, original_filename: str,
                       storage_key: str, size_bytes: int, duration_ms: int | None,
                       asset_id: str) -> dict:
    r = await pool.fetchrow(
        "insert into assets (id, owner_id, original_filename, storage_key, size_bytes, duration_ms, status) "
        "values ($1, $2, $3, $4, $5, $6, 'INITIATED') returning *",
        asset_id, owner_id, original_filename, storage_key, size_bytes, duration_ms,
    )
    return dict(r)


async def get_asset(pool: asyncpg.Pool, asset_id: str, owner_id: str) -> dict | None:
    r = await pool.fetchrow(
        "select * from assets where id = $1 and owner_id = $2 and deleted_at is null",
        asset_id, owner_id,
    )
    return _row(r)


async def list_assets(pool: asyncpg.Pool, owner_id: str) -> list[dict]:
    rows = await pool.fetch(
        "select * from assets where owner_id = $1 and deleted_at is null "
        # Abandoned uploads (browser died before /complete) stop showing after an hour.
        "and (status != 'INITIATED' or created_at > now() - interval '1 hour') "
        "order by created_at desc limit 500",
        owner_id,
    )
    return [dict(r) for r in rows]


async def complete_upload(pool: asyncpg.Pool, asset_id: str, owner_id: str,
                          size_bytes: int) -> dict | None:
    """UPLOADED + three jobs in one transaction. None when the asset doesn't exist."""
    async with pool.acquire() as conn, conn.transaction():
        r = await conn.fetchrow(
            "select * from assets where id = $1 and owner_id = $2 for update",
            asset_id, owner_id,
        )
        if r is None or r["deleted_at"] is not None:
            return None
        if r["status"] not in ("INITIATED", "UPLOADED"):
            raise PermissionError("That upload is already being processed.")
        r = await conn.fetchrow(
            "update assets set size_bytes = $2, status = 'UPLOADED' where id = $1 returning *",
            asset_id, size_bytes,
        )
        await conn.execute(
            "insert into jobs (asset_id, kind) values ($1, 'probe'), ($1, 'thumbnail'), ($1, 'proxy') "
            "on conflict (asset_id, kind) do nothing",
            asset_id,
        )
        return dict(r)


async def soft_delete(pool: asyncpg.Pool, asset_id: str, owner_id: str) -> dict | None:
    """Soft-delete the row; a cleanup job removes the bytes after a grace period."""
    async with pool.acquire() as conn, conn.transaction():
        r = await conn.fetchrow(
            "select * from assets where id = $1 and owner_id = $2 for update",
            asset_id, owner_id,
        )
        if r is None or r["deleted_at"] is not None:
            return None
        r = await conn.fetchrow(
            "update assets set deleted_at = now() where id = $1 returning *",
            asset_id,
        )
        await conn.execute(
            "insert into jobs (asset_id, kind, run_after) values ($1, 'cleanup', now() + $2::interval) "
            "on conflict (asset_id, kind) do update set "
            "  status = 'PENDING', attempts = 0, last_error = null, "
            "  run_after = excluded.run_after, finished_at = null",
            asset_id, timedelta(seconds=CLEANUP_GRACE_SECONDS),
        )
        return dict(r)


# ------------------------------------------------------------------ worker side

async def claim_job(pool: asyncpg.Pool) -> dict | None:
    """Atomically claim the next due job and mark the asset/task RUNNING."""
    async with pool.acquire() as conn, conn.transaction():
        job = await conn.fetchrow(
            "update jobs set status = 'RUNNING', attempts = attempts + 1, started_at = now() "
            "where id = ("
            "  select id from jobs"
            "  where status in ('PENDING', 'FAILED') and run_after <= now() and attempts < $1"
            "  order by created_at"
            "  for update skip locked limit 1"
            ") returning *",
            JOB_MAX_ATTEMPTS,
        )
        if job is None:
            return None
        job = dict(job)
        if job["kind"] == "cleanup":
            # The asset row is (or is about to be) soft-deleted; leave its status alone.
            return job
        col = TASK_COLUMN[job["kind"]]
        await conn.execute(
            f"update assets set status = 'PROCESSING', {col} = 'RUNNING' "
            "where id = $1 and deleted_at is null and status in ('UPLOADED', 'PROCESSING')",
            job["asset_id"],
        )
        return job


async def requeue_stale_jobs(pool: asyncpg.Pool, stale_seconds: int) -> list[dict]:
    """Requeue RUNNING jobs abandoned by a crashed/restarted worker.

    claim_job only picks PENDING/FAILED, so a worker killed mid-job leaves its
    RUNNING row behind forever. Anything RUNNING longer than stale_seconds is
    presumed orphaned and reset to PENDING (attempts preserved — the retry still
    counts against JOB_MAX_ATTEMPTS). Uses SKIP LOCKED so it is safe alongside
    other workers and the claim path.
    """
    async with pool.acquire() as conn, conn.transaction():
        rows = await conn.fetch(
            "update jobs set status = 'PENDING', run_after = now(), started_at = null, "
            "  finished_at = null "
            "where id in ("
            "  select id from jobs where status = 'RUNNING' and started_at < now() - $1::interval"
            "  for update skip locked"
            ") returning id, asset_id, kind, attempts",
            timedelta(seconds=stale_seconds),
        )
        jobs = [dict(r) for r in rows]
        # Clear the asset task columns that were flipped to RUNNING by the dead claim,
        # so the UI shows the retried state honestly (claim_job sets them again on retry).
        for j in jobs:
            col = TASK_COLUMN.get(j["kind"])
            if col:
                await conn.execute(
                    f"update assets set {col} = 'PENDING' "
                    "where id = $1 and deleted_at is null and status = 'PROCESSING'",
                    j["asset_id"],
                )
        return jobs


async def finish_job(pool: asyncpg.Pool, job: dict, *, ok: bool, error: str | None = None,
                     asset_values: dict[str, Any] | None = None) -> str | None:
    """Record the outcome, update the asset task column, and roll up the asset status.

    Returns the asset's new status (or None for cleanup jobs / missing assets).
    """
    kind, asset_id, attempts = job["kind"], job["asset_id"], job["attempts"]
    permanent = attempts_exhausted(attempts)
    error = (error or "")[:2000] or None
    async with pool.acquire() as conn, conn.transaction():
        if ok:
            await conn.execute(
                "update jobs set status = 'DONE', last_error = null, finished_at = now() "
                "where id = $1",
                job["id"],
            )
        elif permanent:
            await conn.execute(
                "update jobs set status = 'FAILED', last_error = $2, finished_at = now() "
                "where id = $1",
                job["id"], error,
            )
        else:
            await conn.execute(
                "update jobs set status = 'FAILED', last_error = $2, "
                "run_after = now() + $3::interval, finished_at = null "
                "where id = $1",
                job["id"], error, timedelta(seconds=backoff_seconds(attempts)),
            )
        if kind == "cleanup":
            return None
        col = TASK_COLUMN[kind]
        values = dict(asset_values or {})
        values[col] = "READY" if ok else ("FAILED" if permanent else "PENDING")
        # jsonb columns (metadata) need a JSON string — asyncpg won't serialize dicts.
        values = {k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in values.items()}
        sets = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(values))
        params = [asset_id, *values.values()]
        r = await conn.fetchrow(
            f"update assets set {sets} where id = $1 and deleted_at is null returning *",
            *params,
        )
        if r is None:
            return None
        status = asset_rollup(r["metadata_status"], r["thumbnail_status"], r["proxy_status"],
                              failed_permanently=ok is False and permanent)
        if status != r["status"]:
            r = await conn.fetchrow(
                "update assets set status = $2 where id = $1 returning status",
                asset_id, status,
            )
        return r["status"] if r else status


async def asset_deleted(pool: asyncpg.Pool, asset_id: str) -> bool:
    r = await pool.fetchrow("select deleted_at from assets where id = $1", asset_id)
    return bool(r and r["deleted_at"] is not None)


async def ping(pool: asyncpg.Pool) -> None:
    await pool.fetchval("select 1")
