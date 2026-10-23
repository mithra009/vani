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
from uuid import uuid4

import asyncpg

from media_service.db import connect  # noqa: F401  same pool rules (no transaction pooler)
from .config import JOB_MAX_ATTEMPTS, JOB_RETRY_BASE_SECONDS
from .errors import Conflict, NotFound

log = logging.getLogger("editor.db")

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

# Lock order, everywhere: the project row first, then its chunks. Every transaction that changes
# a project's chunks takes the project lock up front, so two of them can never hold locks in
# opposite orders (the deadlock the concurrency tests found between set_voice and chunk edits).
# Edits within one project queue for milliseconds; other projects are unaffected.
async def _lock_project(conn, project_id) -> None:
    await conn.execute("select 1 from editor_projects where id = $1 for update", project_id)


async def _lock_project_of_chunk(conn, chunk_id):
    """Lock the project that owns this chunk; returns its id, or None if the chunk is gone."""
    pid = await conn.fetchval("select project_id from chunks where id = $1", chunk_id)
    if pid is not None:
        await _lock_project(conn, pid)
    return pid


async def list_chunks(pool_or_conn, project_id: str, owner_id: str) -> list[dict]:
    rows = await pool_or_conn.fetch(
        "select * from chunks where project_id = $1 and owner_id = $2 order by idx", project_id, owner_id,
    )
    return [_row(r) for r in rows]


async def replace_chunks(pool: asyncpg.Pool, project_id: str, owner_id: str, rows: list[dict],
                         duration_s: float | None) -> list[dict]:
    """Write the generate result and queue one tts job per chunk, atomically."""
    async with pool.acquire() as conn, conn.transaction():
        await _lock_project(conn, project_id)
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
        await _lock_project(conn, project_id)
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
        await _lock_project(conn, project_id)
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
        if await _lock_project_of_chunk(conn, chunk_id) is None:
            return False
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
        if await _lock_project_of_chunk(conn, chunk_id) is None:
            return
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
    """Fair claiming: the job whose owner has the fewest jobs running goes next, so one user's
    200 queued chunks can't starve someone else's 3. Then whole-project jobs before chunk tts,
    then oldest first."""
    r = await pool.fetchrow(
        "update editor_jobs set status = 'RUNNING', attempts = attempts + 1, started_at = now() "
        "where id = ("
        "  select j.id from editor_jobs j"
        "  where j.status in ('PENDING', 'FAILED') and j.run_after <= now() and j.attempts < $1"
        "  order by (select count(*) from editor_jobs r where r.owner_id = j.owner_id and r.status = 'RUNNING'),"
        "           (j.kind = 'tts'), j.created_at"
        "  for update skip locked limit 1"
        ") returning *",
        JOB_MAX_ATTEMPTS,
    )
    return _row(r)


async def defer_job(pool: asyncpg.Pool, job: dict, delay_s: float, reason: str) -> None:
    """Put a rate-limited job back in the queue for later. It doesn't count as an attempt."""
    await pool.execute(
        "update editor_jobs set status = 'PENDING', attempts = greatest(attempts - 1, 0), started_at = null, "
        "  run_after = now() + make_interval(secs => $2), last_error = $3 where id = $1",
        job["id"], float(delay_s), reason[:500],
    )


async def user_counts(pool: asyncpg.Pool, owner_id: str) -> dict:
    """What the per-user limits look at, in one round trip."""
    r = await pool.fetchrow(
        "select (select count(*) from editor_projects where owner_id = $1 and deleted_at is null) as projects, "
        "  (select count(*) from editor_projects where owner_id = $1 and deleted_at is null and status = 'generating') as generating, "
        "  (select count(*) from exports where owner_id = $1 and status in ('queued', 'rendering')) as exports, "
        "  (select count(distinct owner_id) from editor_jobs where status in ('PENDING', 'RUNNING')) as active_users",
        owner_id,
    )
    return dict(r)


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


# Which migration creates each table/column the service needs.
REQUIRED_SCHEMA = {
    "assets": "002_media_assets.sql",
    "editor_projects": "004_editor_projects.sql",
    "chunks": "004_editor_projects.sql",
    "artifacts": "004_editor_projects.sql",
    "editor_jobs": "004_editor_projects.sql",
    "timelines": "005_editor_timeline.sql",
    "timeline_ops": "005_editor_timeline.sql",
    "project_media": "005_editor_timeline.sql",
    "exports": "006_editor_exports.sql",
    "provider_calls": "007_rate_limits.sql",
}


async def check_schema(pool: asyncpg.Pool) -> None:
    """Fail at startup with the migration to apply, not with a traceback on every poll."""
    rows = await pool.fetch(
        "select table_name from information_schema.tables where table_schema = 'public' and table_name = any($1::text[])",
        list(REQUIRED_SCHEMA),
    )
    missing = [t for t in REQUIRED_SCHEMA if t not in {r["table_name"] for r in rows}]
    if not missing:
        has_export_col = await pool.fetchval(
            "select 1 from information_schema.columns where table_schema = 'public' "
            "and table_name = 'editor_jobs' and column_name = 'export_id'")
        if not has_export_col:
            missing = ["editor_jobs.export_id"]
            REQUIRED_SCHEMA["editor_jobs.export_id"] = "006_editor_exports.sql"
    if missing:
        files = sorted({REQUIRED_SCHEMA[t] for t in missing})
        raise RuntimeError(
            f"Database schema is missing {', '.join(missing)}. Apply {', '.join(files)} "
            "(supabase/migrations/, in order) in the Supabase SQL editor, then restart."
        )


# ------------------------------------------------------------------ timeline (phase 2)

def _doc(raw) -> dict:
    return json.loads(raw) if isinstance(raw, str) else raw


async def get_timeline(conn, project_id: str, owner_id: str, default_doc, *, lock: bool = False) -> dict:
    """The project's timeline; created from default_doc(duration_s) on first read."""
    q = "select version, doc from timelines where project_id = $1 and owner_id = $2" + (" for update" if lock else "")
    r = await conn.fetchrow(q, project_id, owner_id)
    if r is None:
        p = await get_project(conn, project_id, owner_id)
        await conn.execute(
            "insert into timelines (project_id, owner_id, doc) values ($1, $2, $3::jsonb) on conflict do nothing",
            project_id, owner_id, json.dumps(default_doc(float(p["duration_s"] or 0))),
        )
        r = await conn.fetchrow(q, project_id, owner_id)
    return {"version": r["version"], "doc": _doc(r["doc"])}


class VersionConflict(Conflict):
    """409 carrying the current timeline so the client can rebase without another round trip."""

    def __init__(self, current: dict):
        super().__init__(f"The timeline changed (now version {current['version']}). Rebase and retry.")
        self.current = current


async def save_timeline(pool: asyncpg.Pool, project_id: str, owner_id: str, base_version: int,
                        apply_fn, default_doc) -> dict:
    """apply_fn(conn, doc) -> (new_doc, ops). Locked read-modify-write; VersionConflict when stale."""
    async with pool.acquire() as conn, conn.transaction():
        current = await get_timeline(conn, project_id, owner_id, default_doc, lock=True)
        if current["version"] != base_version:
            raise VersionConflict(current)
        doc, ops = await apply_fn(conn, current["doc"])
        version = base_version + 1
        await conn.execute(
            "update timelines set doc = $2::jsonb, version = $3, updated_at = now() where project_id = $1",
            project_id, json.dumps(doc), version,
        )
        await conn.execute(
            "insert into timeline_ops (project_id, version, ops) values ($1, $2, $3::jsonb)",
            project_id, version, json.dumps(ops),
        )
        return {"version": version, "doc": doc}


# ------------------------------------------------------------------ music media (phase 2)

async def media_init(pool: asyncpg.Pool, project_id: str, owner_id: str, filename: str, ext: str,
                     duration_s: float) -> dict:
    await get_project(pool, project_id, owner_id)
    mid = str(uuid4())
    return _row(await pool.fetchrow(
        "insert into project_media (id, project_id, owner_id, storage_key, filename, duration_s) "
        "values ($1, $2, $3, $4, $5, $6) returning *",
        mid, project_id, owner_id, f"{owner_id}/projects/{project_id}/music/{mid}.{ext}", filename, duration_s,
    ))


async def media_ready(pool: asyncpg.Pool, project_id: str, owner_id: str, media_id: str) -> dict:
    r = await pool.fetchrow(
        "update project_media set status = 'READY' where id = $1 and project_id = $2 and owner_id = $3 returning *",
        media_id, project_id, owner_id,
    )
    if r is None:
        raise NotFound("That audio file doesn't exist.")
    return _row(r)


async def list_media(conn, project_id: str, owner_id: str, *, ready_only: bool = True) -> list[dict]:
    rows = await conn.fetch(
        "select * from project_media where project_id = $1 and owner_id = $2 "
        "and (not $3 or status = 'READY') order by created_at",
        project_id, owner_id, ready_only,
    )
    return [_row(r) for r in rows]


# ------------------------------------------------------------------ split / merge (C4-proposal: text-level)

async def _pack(conn, project_id: str, ordered_ids: list) -> None:
    """Rewrite idx to 0..n-1 in the given order. Park every row on a distinct negative first
    so the (project_id, idx) unique index never sees a duplicate mid-update."""
    await conn.execute("update chunks set idx = -1 - idx where project_id = $1 and idx >= 0", project_id)
    await conn.executemany("update chunks set idx = $2 where id = $1", [(cid, n) for n, cid in enumerate(ordered_ids)])


async def _ordered_ids(conn, project_id: str) -> list:
    return [r["id"] for r in await conn.fetch("select id from chunks where project_id = $1 order by idx", project_id)]


async def _after_content_change(conn, project_id: str, owner_id: str, chunk_ids: list) -> list[dict]:
    out = []
    for cid in chunk_ids:
        r = await conn.fetchrow("select * from chunks where id = $1", cid)
        await _enqueue_tts(conn, project_id, owner_id, r["id"], r["revision"])
        out.append(_row(r))
    await conn.execute("update editor_projects set status = 'generating' where id = $1 and status = 'editing'", project_id)
    return out


async def split_chunk(pool: asyncpg.Pool, project_id: str, owner_id: str, chunk_id: str, revision: int,
                      at_char: int) -> list[dict]:
    """Split one chunk's text at a character; both halves regenerate. The source span and the
    anchor are divided in proportion to the text lengths (an estimate the user can drag)."""
    async with pool.acquire() as conn, conn.transaction():
        await _lock_project(conn, project_id)
        c = await conn.fetchrow(
            "select * from chunks where id = $1 and project_id = $2 and owner_id = $3 for update",
            chunk_id, project_id, owner_id,
        )
        if c is None:
            raise NotFound("That chunk doesn't exist.")
        if c["revision"] != revision:
            raise Conflict(f"This chunk changed since you loaded it (revision {c['revision']}, you sent {revision}).")
        left, right = c["text"][:at_char].strip(), c["text"][at_char:].strip()
        if not left or not right:
            raise ValueError("The split point must leave text on both sides.")
        frac = len(left) / (len(left) + len(right))
        span = c["char_end"] - c["char_start"]
        cut = max(1, min(span - 1, round(span * frac))) if span > 1 else None
        if cut is None:
            raise ValueError("This chunk is too short to split.")
        src_l, src_r = c["source_text"][:cut].strip(), c["source_text"][cut:].strip()
        a0 = float(c["anchor_src_s"]) if c["anchor_src_s"] is not None else None
        alen = float(c["anchor_len_s"]) if c["anchor_len_s"] is not None else None
        await conn.execute(
            "update chunks set text = $2, source_text = $3, char_end = $4, anchor_len_s = $5, revision = revision + 1, "
            "  status = 'pending', error_code = null, error_message = null where id = $1",
            c["id"], left, src_l or c["source_text"][:cut], c["char_start"] + cut,
            round(alen * frac, 3) if alen is not None else None,
        )
        new = await conn.fetchrow(
            "insert into chunks (project_id, owner_id, idx, source_text, char_start, char_end, text, "
            "  anchor_src_s, anchor_len_s, overflow, emotion_tag, speed) "
            "values ($1, $2, -1000000, $3, $4, $5, $6, $7, $8, $9, $10, $11) returning id",
            project_id, owner_id, src_r or c["source_text"][cut:], c["char_start"] + cut, c["char_end"], right,
            round(a0 + alen * frac, 3) if a0 is not None and alen is not None else None,
            round(alen * (1 - frac), 3) if alen is not None else None,
            c["overflow"], c["emotion_tag"], c["speed"],
        )
        order = [i for i in await _ordered_ids(conn, project_id) if i != new["id"]]
        order.insert(order.index(c["id"]) + 1, new["id"])
        await _pack(conn, project_id, order)
        return await _after_content_change(conn, project_id, owner_id, [c["id"], new["id"]])


async def merge_chunks(pool: asyncpg.Pool, project_id: str, owner_id: str, first_id: str, first_rev: int,
                       second_id: str, second_rev: int) -> dict:
    """Merge a chunk with the one right after it; the first regenerates, the second is deleted."""
    async with pool.acquire() as conn, conn.transaction():
        await _lock_project(conn, project_id)
        rows = await conn.fetch(
            "select * from chunks where id = any($1::uuid[]) and project_id = $2 and owner_id = $3 for update",
            [first_id, second_id], project_id, owner_id,
        )
        by = {str(r["id"]): r for r in rows}
        a, b = by.get(str(first_id)), by.get(str(second_id))
        if a is None or b is None:
            raise NotFound("That chunk doesn't exist.")
        if (a["revision"], b["revision"]) != (first_rev, second_rev):
            raise Conflict("One of these chunks changed since you loaded it.")
        if b["idx"] != a["idx"] + 1:
            raise ValueError("Only neighbouring chunks can be merged (a chunk and the one after it).")
        alen = None
        if None not in (a["anchor_src_s"], b["anchor_src_s"], b["anchor_len_s"]):
            alen = round(float(b["anchor_src_s"]) + float(b["anchor_len_s"]) - float(a["anchor_src_s"]), 3)
        await conn.execute("delete from chunks where id = $1", b["id"])
        await conn.execute(
            "update chunks set text = $2, source_text = $3, char_end = $4, anchor_len_s = coalesce($5, anchor_len_s), "
            "  overflow = overflow or $6, revision = revision + 1, status = 'pending', "
            "  error_code = null, error_message = null where id = $1",
            a["id"], f"{a['text']} {b['text']}", f"{a['source_text']} {b['source_text']}", b["char_end"], alen,
            b["overflow"],
        )
        await _pack(conn, project_id, await _ordered_ids(conn, project_id))
        return (await _after_content_change(conn, project_id, owner_id, [a["id"]]))[0]


# ------------------------------------------------------------------ exports (phase 3)

async def create_export(pool: asyncpg.Pool, project_id: str, owner_id: str, *, timeline_version: int,
                        fmt: str, height: int | None, audio_mix: str, captions: str, snapshot: dict,
                        content_key: str) -> dict:
    """Queue a render — or, when an identical export already exists, return a ready copy (cache)."""
    async with pool.acquire() as conn, conn.transaction():
        cached = await conn.fetchrow(
            "select * from exports where owner_id = $1 and content_key = $2 and status = 'ready' "
            "order by finished_at desc limit 1",
            owner_id, content_key,
        )
        e = await conn.fetchrow(
            "insert into exports (project_id, owner_id, timeline_version, format, height, audio_mix, captions, "
            "  snapshot, content_key, status, progress, warnings, output_key, captions_key, finished_at) "
            "values ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10, $11, $12::jsonb, $13, $14, $15) returning *",
            project_id, owner_id, timeline_version, fmt, height, audio_mix, captions, json.dumps(snapshot), content_key,
            "ready" if cached else "queued", 1.0 if cached else 0.0,
            json.dumps(_doc(cached["warnings"])) if cached else "[]",
            cached["output_key"] if cached else None, cached["captions_key"] if cached else None,
            cached["finished_at"] if cached else None,
        )
        if not cached:
            await conn.execute(
                "insert into editor_jobs (project_id, owner_id, kind, export_id) values ($1, $2, 'export', $3)",
                project_id, owner_id, e["id"],
            )
        return _export_row(e)


def _export_row(r) -> dict | None:
    d = _row(r)
    if d is not None:
        for k in ("snapshot", "warnings"):
            if isinstance(d.get(k), str):
                d[k] = json.loads(d[k])
    return d


async def list_exports(pool: asyncpg.Pool, project_id: str, owner_id: str) -> list[dict]:
    rows = await pool.fetch(
        "select id, project_id, timeline_version, format, height, audio_mix, captions, status, progress, warnings, "
        "  output_key, captions_key, error_code, error_message, created_at, finished_at "
        "from exports where project_id = $1 and owner_id = $2 order by created_at desc limit 50",
        project_id, owner_id,
    )
    return [_export_row(r) for r in rows]


async def get_export(pool_or_conn, export_id: str, owner_id: str | None = None) -> dict:
    r = await pool_or_conn.fetchrow(
        "select * from exports where id = $1 and ($2::uuid is null or owner_id = $2::uuid)", export_id, owner_id,
    )
    if r is None:
        raise NotFound("That export doesn't exist.")
    return _export_row(r)


async def export_progress(pool: asyncpg.Pool, export_id: str, progress: float, status: str = "rendering") -> None:
    await pool.execute(
        "update exports set status = $3, progress = $2 where id = $1 and status in ('queued', 'rendering')",
        export_id, max(0.0, min(1.0, progress)), status,
    )


async def export_done(pool: asyncpg.Pool, export_id: str, output_key: str, captions_key: str | None,
                      warnings: list) -> None:
    await pool.execute(
        "update exports set status = 'ready', progress = 1, output_key = $2, captions_key = $3, warnings = $4::jsonb, "
        "  finished_at = now(), error_code = null, error_message = null where id = $1",
        export_id, output_key, captions_key, json.dumps(warnings),
    )


async def export_failed(pool: asyncpg.Pool, export_id: str, code: str, message: str) -> None:
    await pool.execute(
        "update exports set status = 'failed', error_code = $2, error_message = $3, finished_at = now() where id = $1",
        export_id, code, message[:2000],
    )
