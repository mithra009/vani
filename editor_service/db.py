"""asyncpg access for editor projects, chunks, artifacts and the editor_jobs queue.

Every query filters by owner_id (defence in depth on top of RLS). State changes that need
work done enqueue their job in the same transaction, so a crash can't leave a project
"generating" with nothing queued.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

import asyncpg

from media_service.db import connect  # same pool rules (no transaction pooler)
from .config import JOB_MAX_ATTEMPTS, JOB_RETRY_BASE_SECONDS
from .errors import Conflict, NotFound

log = logging.getLogger("editor.db")

__all__ = ["connect"]

ACTIVE_CHUNK = ("pending", "generating")


def _row(r: asyncpg.Record | None) -> dict | None:
    if r is None:
        return None
    d = dict(r)
    for k in ("voice", "meta"):
        if isinstance(d.get(k), str):
            d[k] = json.loads(d[k])
    return d


def backoff_seconds(attempts: int) -> int:
    return JOB_RETRY_BASE_SECONDS * 2 ** max(0, attempts - 1)


# ------------------------------------------------------------------ projects

async def asset_for_owner(pool: asyncpg.Pool, asset_id: str, owner_id: str) -> dict | None:
    return _row(await pool.fetchrow(
        "select id, storage_key, status, duration_ms from assets "
        "where id = $1 and owner_id = $2 and deleted_at is null",
        asset_id, owner_id,
    ))


async def create_project(pool: asyncpg.Pool, owner_id: str, *, asset_id: str, name: str,
                         input_kind: str, script_text: str | None, src_lang: str, tgt_lang: str,
                         voice: dict, duration_s: float | None) -> dict:
    """Narration waits for its one take (D12); the other kinds start generating at once."""
    status = "awaiting_narration" if input_kind == "narration" else "generating"
    async with pool.acquire() as conn, conn.transaction():
        p = await conn.fetchrow(
            "insert into editor_projects (owner_id, asset_id, name, input_kind, script_text, "
            "  src_lang, tgt_lang, voice, duration_s, status) "
            "values ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10) returning *",
            owner_id, asset_id, name, input_kind, script_text, src_lang, tgt_lang,
            json.dumps(voice), duration_s, status,
        )
        if status == "generating":
            await _enqueue_generate(conn, p["id"], owner_id)
        return _row(p)


async def get_project(pool_or_conn, project_id: str, owner_id: str) -> dict:
    p = _row(await pool_or_conn.fetchrow(
        "select * from editor_projects where id = $1 and owner_id = $2 and deleted_at is null",
        project_id, owner_id,
    ))
    if p is None:
        raise NotFound("That project doesn't exist.")
    return p


async def list_projects(pool: asyncpg.Pool, owner_id: str) -> list[dict]:
    rows = await pool.fetch(
        "select * from editor_projects where owner_id = $1 and deleted_at is null "
        "order by created_at desc limit 200",
        owner_id,
    )
    return [_row(r) for r in rows]


async def soft_delete_project(pool: asyncpg.Pool, project_id: str, owner_id: str) -> None:
    r = await pool.execute(
        "update editor_projects set deleted_at = now() where id = $1 and owner_id = $2 and deleted_at is null",
        project_id, owner_id,
    )
    if r.endswith(" 0"):
        raise NotFound("That project doesn't exist.")


async def narration_uploaded(pool: asyncpg.Pool, project_id: str, owner_id: str, key: str) -> dict:
    async with pool.acquire() as conn, conn.transaction():
        p = await conn.fetchrow(
            "select * from editor_projects where id = $1 and owner_id = $2 and deleted_at is null for update",
            project_id, owner_id,
        )
        if p is None:
            raise NotFound("That project doesn't exist.")
        if p["status"] != "awaiting_narration":
            raise Conflict("This project already has its narration (one take only).")
        p = await conn.fetchrow(
            "update editor_projects set narration_key = $2, status = 'generating', "
            "  error_code = null, error_message = null where id = $1 returning *",
            project_id, key,
        )
        await _enqueue_generate(conn, project_id, owner_id)
        return _row(p)


async def retry_generate(pool: asyncpg.Pool, project_id: str, owner_id: str) -> dict:
    async with pool.acquire() as conn, conn.transaction():
        p = await conn.fetchrow(
            "select * from editor_projects where id = $1 and owner_id = $2 and deleted_at is null for update",
            project_id, owner_id,
        )
        if p is None:
            raise NotFound("That project doesn't exist.")
        if p["status"] != "failed":
            raise Conflict(f"Only a failed project can be retried (this one is {p['status']}).")
        p = await conn.fetchrow(
            "update editor_projects set status = 'generating', error_code = null, error_message = null "
            "where id = $1 returning *",
            project_id,
        )
        await _enqueue_generate(conn, project_id, owner_id)
        return _row(p)


async def set_voice(pool: asyncpg.Pool, project_id: str, owner_id: str, voice: dict,
                    settings_version: int) -> dict:
    """Changing the one project voice (D8) regenerates every chunk."""
    async with pool.acquire() as conn, conn.transaction():
        p = await conn.fetchrow(
            "update editor_projects set voice = $3::jsonb, settings_version = settings_version + 1 "
            "where id = $1 and owner_id = $2 and deleted_at is null and settings_version = $4 "
            "  and status in ('editing', 'generating') returning *",
            project_id, owner_id, json.dumps(voice), settings_version,
        )
        if p is None:
            await get_project(conn, project_id, owner_id)
            raise Conflict("The project changed since you loaded it, or isn't ready for a voice change. Reload and try again.")
        chunks = await conn.fetch(
            "update chunks set revision = revision + 1, status = 'pending', error_code = null, error_message = null "
            "where project_id = $1 returning id, revision",
            project_id,
        )
        for c in chunks:
            await _enqueue_tts(conn, project_id, owner_id, c["id"], c["revision"])
        if chunks:
            p = await conn.fetchrow("update editor_projects set status = 'generating' where id = $1 returning *", project_id)
        return _row(p)


async def fail_project(pool: asyncpg.Pool, project_id: str, code: str, message: str) -> None:
    await pool.execute(
        "update editor_projects set status = 'failed', error_code = $2, error_message = $3 where id = $1",
        project_id, code, message[:2000],
    )


async def settle_project(conn, project_id: str) -> None:
    """generating → editing once no chunk is pending/generating (failed chunks stay visible)."""
    await conn.execute(
        "update editor_projects set status = 'editing' where id = $1 and status = 'generating' "
        "and exists (select 1 from chunks where project_id = $1) "
        "and not exists (select 1 from chunks where project_id = $1 and status = any($2::text[]))",
        project_id, list(ACTIVE_CHUNK),
    )


# ------------------------------------------------------------------ chunks

async def list_chunks(pool_or_conn, project_id: str, owner_id: str) -> list[dict]:
    rows = await pool_or_conn.fetch(
        "select * from chunks where project_id = $1 and owner_id = $2 order by idx", project_id, owner_id,
    )
    return [_row(r) for r in rows]


async def replace_chunks(pool: asyncpg.Pool, project_id: str, owner_id: str, rows: list[dict],
                         duration_s: float | None) -> list[dict]:
    """Write the generate result and queue one tts job per chunk, atomically."""
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("delete from chunks where project_id = $1", project_id)
        out = []
        for r in rows:
            c = await conn.fetchrow(
                "insert into chunks (project_id, owner_id, idx, source_text, char_start, char_end, text, "
                "  anchor_src_s, anchor_len_s, overflow, emotion_tag) "
                "values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) returning *",
                project_id, owner_id, r["idx"], r["source_text"], r["char_start"], r["char_end"], r["text"],
                r["anchor_src_s"], r["anchor_len_s"], r["overflow"], r["emotion_tag"],
            )
            await _enqueue_tts(conn, project_id, owner_id, c["id"], c["revision"])
            out.append(_row(c))
        if duration_s is not None:
            await conn.execute("update editor_projects set duration_s = $2 where id = $1", project_id, duration_s)
        return out


async def edit_chunk(pool: asyncpg.Pool, project_id: str, owner_id: str, chunk_id: str,
                     revision: int, changes: dict[str, Any]) -> dict:
    """Content edit (text / emotion / speed) with optimistic locking → regenerate this chunk only."""
    allowed = {"text", "emotion_tag", "speed"}
    if not changes or set(changes) - allowed:
        raise ValueError(f"Editable fields are {sorted(allowed)}.")
    sets = ", ".join(f"{k} = ${i + 5}" for i, k in enumerate(changes))
    async with pool.acquire() as conn, conn.transaction():
        c = await conn.fetchrow(
            f"update chunks set {sets}, revision = revision + 1, status = 'pending', "
            "  error_code = null, error_message = null "
            "where id = $1 and project_id = $2 and owner_id = $3 and revision = $4 returning *",
            chunk_id, project_id, owner_id, revision, *changes.values(),
        )
        if c is None:
            cur = await conn.fetchrow(
                "select revision from chunks where id = $1 and project_id = $2 and owner_id = $3",
                chunk_id, project_id, owner_id,
            )
            if cur is None:
                raise NotFound("That chunk doesn't exist.")
            raise Conflict(f"This chunk changed since you loaded it (revision {cur['revision']}, you sent {revision}).")
        await _enqueue_tts(conn, project_id, owner_id, chunk_id, c["revision"])
        await conn.execute("update editor_projects set status = 'generating' where id = $1 and status = 'editing'", project_id)
        return _row(c)


async def regenerate_chunk(pool: asyncpg.Pool, project_id: str, owner_id: str, chunk_id: str) -> dict:
    """Retry a failed chunk (or re-roll a ready one) without changing its content."""
    async with pool.acquire() as conn, conn.transaction():
        c = await conn.fetchrow(
            "update chunks set revision = revision + 1, status = 'pending', error_code = null, error_message = null "
            "where id = $1 and project_id = $2 and owner_id = $3 and status in ('ready', 'failed') returning *",
            chunk_id, project_id, owner_id,
        )
        if c is None:
            cur = await conn.fetchrow(
                "select status from chunks where id = $1 and project_id = $2 and owner_id = $3",
                chunk_id, project_id, owner_id,
            )
            if cur is None:
                raise NotFound("That chunk doesn't exist.")
            raise Conflict("That chunk is already being generated.")
        await _enqueue_tts(conn, project_id, owner_id, chunk_id, c["revision"])
        await conn.execute("update editor_projects set status = 'generating' where id = $1 and status = 'editing'", project_id)
        return _row(c)


async def chunk_audio_ready(pool: asyncpg.Pool, chunk_id: str, revision: int, audio_key: str,
                            duration_s: float) -> bool:
    """Stale-result guard: only the job for the current revision may write. False → stale."""
    async with pool.acquire() as conn, conn.transaction():
        c = await conn.fetchrow(
            "update chunks set audio_key = $3, audio_duration_s = $4, status = 'ready' "
            "where id = $1 and revision = $2 returning project_id",
            chunk_id, revision, audio_key, duration_s,
        )
        if c is None:
            return False
        await settle_project(conn, c["project_id"])
        return True


async def chunk_failed(pool: asyncpg.Pool, chunk_id: str, revision: int, code: str, message: str) -> None:
    async with pool.acquire() as conn, conn.transaction():
        c = await conn.fetchrow(
            "update chunks set status = 'failed', error_code = $3, error_message = $4 "
            "where id = $1 and revision = $2 returning project_id",
            chunk_id, revision, code, message[:2000],
        )
        if c is not None:
            await settle_project(conn, c["project_id"])


async def chunk_generating(pool: asyncpg.Pool, chunk_id: str, revision: int) -> dict | None:
    """Mark the chunk generating and return it, or None when the job is stale."""
    return _row(await pool.fetchrow(
        "update chunks set status = 'generating' where id = $1 and revision = $2 "
        "and status in ('pending', 'generating') returning *",
        chunk_id, revision,
    ))


# ------------------------------------------------------------------ artifacts

async def artifact_get(pool: asyncpg.Pool, owner_id: str, key: str) -> dict | None:
    return _row(await pool.fetchrow(
        "update artifacts set last_used_at = now() where owner_id = $1 and content_key = $2 returning *",
        owner_id, key,
    ))


async def artifact_put(pool: asyncpg.Pool, owner_id: str, key: str, kind: str, storage_key: str,
                       meta: dict) -> None:
    await pool.execute(
        "insert into artifacts (owner_id, content_key, kind, storage_key, meta) values ($1, $2, $3, $4, $5::jsonb) "
        "on conflict (owner_id, content_key) do update set last_used_at = now()",
        owner_id, key, kind, storage_key, json.dumps(meta),
    )


# ------------------------------------------------------------------ queue

async def _enqueue_generate(conn, project_id: str, owner_id: str) -> None:
    await conn.execute(
        "insert into editor_jobs (project_id, owner_id, kind) values ($1, $2, 'generate')",
        project_id, owner_id,
    )


async def _enqueue_tts(conn, project_id: str, owner_id: str, chunk_id: str, revision: int) -> None:
    # Older pending tts jobs for this chunk are now stale; skip them instead of running them.
    await conn.execute(
        "update editor_jobs set status = 'SKIPPED', last_error = 'superseded by a newer revision', "
        "  finished_at = now() "
        "where chunk_id = $1 and kind = 'tts' and status in ('PENDING', 'FAILED')",
        chunk_id,
    )
    await conn.execute(
        "insert into editor_jobs (project_id, owner_id, kind, chunk_id, chunk_revision) "
        "values ($1, $2, 'tts', $3, $4)",
        project_id, owner_id, chunk_id, revision,
    )


async def claim_job(pool: asyncpg.Pool) -> dict | None:
    """Whole-project generate jobs first, then chunk tts jobs, oldest first."""
    r = await pool.fetchrow(
        "update editor_jobs set status = 'RUNNING', attempts = attempts + 1, started_at = now() "
        "where id = ("
        "  select id from editor_jobs"
        "  where status in ('PENDING', 'FAILED') and run_after <= now() and attempts < $1"
        "  order by (kind = 'tts'), created_at"
        "  for update skip locked limit 1"
        ") returning *",
        JOB_MAX_ATTEMPTS,
    )
    return _row(r)


async def finish_job(pool: asyncpg.Pool, job: dict, *, outcome: str, code: str | None = None,
                     error: str | None = None, retry: bool = False) -> bool:
    """outcome: DONE | SKIPPED | FAILED. Returns True when the failure is final (no more retries)."""
    error = (error or "")[:2000] or None
    final = outcome != "FAILED" or not retry or job["attempts"] >= JOB_MAX_ATTEMPTS
    if outcome == "FAILED" and not final:
        await pool.execute(
            "update editor_jobs set status = 'FAILED', error_code = $2, last_error = $3, "
            "  run_after = now() + $4::interval, finished_at = null where id = $1",
            job["id"], code, error, timedelta(seconds=backoff_seconds(job["attempts"])),
        )
        return False
    # A final failure must never be claimed again: push attempts to the cap.
    await pool.execute(
        "update editor_jobs set status = $2, error_code = $3, last_error = $4, finished_at = now(), "
        "  attempts = case when $2 = 'FAILED' then greatest(attempts, $5) else attempts end "
        "where id = $1",
        job["id"], outcome, code, error, JOB_MAX_ATTEMPTS,
    )
    return outcome == "FAILED"


async def requeue_stale_jobs(pool: asyncpg.Pool, stale_seconds: int) -> list[dict]:
    rows = await pool.fetch(
        "update editor_jobs set status = 'PENDING', run_after = now(), started_at = null "
        "where id in ("
        "  select id from editor_jobs where status = 'RUNNING' and started_at < now() - $1::interval"
        "  for update skip locked"
        ") returning id, project_id, kind, attempts",
        timedelta(seconds=stale_seconds),
    )
    return [dict(r) for r in rows]


async def project_for_job(pool: asyncpg.Pool, job: dict) -> dict | None:
    return _row(await pool.fetchrow(
        "select p.*, a.storage_key as asset_key from editor_projects p "
        "join assets a on a.id = p.asset_id where p.id = $1 and p.deleted_at is null",
        job["project_id"],
    ))


async def ping(pool: asyncpg.Pool) -> None:
    await pool.fetchval("select 1")
