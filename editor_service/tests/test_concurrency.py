"""Concurrency and race conditions against a real Postgres (the real migrations, many parallel
connections). Each test fires the racing operations at the same moment and then checks the
invariants that must hold however the scheduler interleaved them.

Runs only with DATABASE_URL_TEST (see test_db.py); the database is wiped.
"""

import asyncio
import random
import uuid

import asyncpg
import pytest

from editor_service import db, timeline
from editor_service.errors import Conflict, NotFound
from editor_service.tests.test_db import OWNER, ROWS, URL, editing_project, fresh_pool, new_project

pytestmark = pytest.mark.skipif(not URL, reason="DATABASE_URL_TEST not set")


def run(coro):
    return asyncio.run(coro)


async def wide_pool():
    """Migrations + a pool wide enough that racers really run in parallel."""
    p = await fresh_pool()
    await p.close()
    return await asyncpg.create_pool(URL, min_size=16, max_size=24)


async def race(n, make):
    """Start n coroutines at the same instant; return (results, exceptions)."""
    gate = asyncio.Event()

    async def one(i):
        await gate.wait()
        return await make(i)
    tasks = [asyncio.create_task(one(i)) for i in range(n)]
    await asyncio.sleep(0.05)
    gate.set()
    out = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in out if not isinstance(r, BaseException)], [r for r in out if isinstance(r, BaseException)]


def only(errors, *types):
    unexpected = [e for e in errors if not isinstance(e, types)]
    assert not unexpected, f"unexpected errors: {unexpected[:3]}"


# ------------------------------------------------------------------ job queue

def test_each_job_is_claimed_exactly_once():
    async def go():
        pool = await wide_pool()
        try:
            p = await new_project(pool)
            await db.finish_job(pool, await db.claim_job(pool), outcome="DONE")
            pid = str(p["id"])
            await pool.executemany(
                "insert into editor_jobs (project_id, owner_id, kind) values ($1, $2, 'generate')",
                [(pid, OWNER)] * 60)
            claimed = []

            async def worker(_):
                while (j := await db.claim_job(pool)) is not None:
                    claimed.append(j["id"])
                    await asyncio.sleep(random.random() / 200)
                    await db.finish_job(pool, j, outcome="DONE")
            _, errs = await race(12, worker)
            only(errs)
            assert len(claimed) == 60 and len(set(claimed)) == 60
            assert await pool.fetchval("select count(*) from editor_jobs where status <> 'DONE'") == 0
        finally:
            await pool.close()
    run(go())


def test_reaper_never_hands_a_running_job_to_a_second_worker():
    async def go():
        pool = await wide_pool()
        try:
            p = await new_project(pool)
            await db.finish_job(pool, await db.claim_job(pool), outcome="DONE")
            await pool.executemany("insert into editor_jobs (project_id, owner_id, kind) values ($1, $2, 'generate')",
                                   [(str(p["id"]), OWNER)] * 30)
            claims = []

            async def make(i):
                if i % 4 == 0:                      # reapers (stale = older than 1 h: none should be)
                    for _ in range(20):
                        await db.requeue_stale_jobs(pool, 3600)
                    return
                while (j := await db.claim_job(pool)) is not None:
                    claims.append(j["id"])
            _, errs = await race(12, make)
            only(errs)
            assert len(claims) == len(set(claims)) == 30
        finally:
            await pool.close()
    run(go())


# ------------------------------------------------------------------ optimistic locking

def test_simultaneous_edits_of_one_revision_exactly_one_wins():
    async def go():
        pool = await wide_pool()
        try:
            pid, cs = await editing_project(pool)
            cid = str(cs[0]["id"])
            ok, errs = await race(10, lambda i: db.edit_chunk(pool, pid, OWNER, cid, 1, {"text": f"version {i}"}))
            only(errs, Conflict)
            assert len(ok) == 1 and len(errs) == 9
            row = await pool.fetchrow("select revision, text, status from chunks where id = $1", cid)
            assert row["revision"] == 2 and row["text"] == ok[0]["text"] and row["status"] == "pending"
            live = await pool.fetchval("select count(*) from editor_jobs where chunk_id = $1 and status = 'PENDING'", cid)
            assert live == 1
        finally:
            await pool.close()
    run(go())


def test_simultaneous_timeline_saves_exactly_one_wins():
    async def go():
        pool = await wide_pool()
        try:
            pid, _ = await editing_project(pool)
            await db.get_timeline(pool, pid, OWNER, timeline.default_doc)

            def save(i):
                async def apply_fn(conn, doc):
                    d, _ = timeline.apply_all(doc, [{"type": "track.set", "track": "original_audio",
                                                     "fields": {"gain_db": -float(i)}}], source_s=6.0)
                    return d, [f"op{i}"]
                return db.save_timeline(pool, pid, OWNER, 1, apply_fn, timeline.default_doc)
            ok, errs = await race(10, save)
            only(errs, db.VersionConflict)
            assert len(ok) == 1 and len(errs) == 9
            assert all(e.current["version"] == 2 for e in errs)        # every loser gets the winner's doc to rebase on
            assert await pool.fetchval("select count(*) from timeline_ops where project_id = $1", pid) == 1
            tl = await db.get_timeline(pool, pid, OWNER, timeline.default_doc)
            assert tl["version"] == 2 and tl["doc"] == ok[0]["doc"]
        finally:
            await pool.close()
    run(go())


def test_simultaneous_voice_changes_exactly_one_applies():
    async def go():
        pool = await wide_pool()
        try:
            pid, _ = await editing_project(pool)
            ok, errs = await race(8, lambda i: db.set_voice(pool, pid, OWNER, {"mode": "persona", "voice_id": f"v{i}"}, 1))
            only(errs, Conflict)
            assert len(ok) == 1
            p = await db.get_project(pool, pid, OWNER)
            assert p["settings_version"] == 2 and p["voice"] == ok[0]["voice"]
            # every chunk re-voiced once, at revision 2, with one live job each
            assert await pool.fetchval("select count(*) from editor_jobs where status = 'PENDING' and kind = 'tts'") == len(ROWS)
        finally:
            await pool.close()
    run(go())


def test_narration_one_take_under_concurrency():
    async def go():
        pool = await wide_pool()
        try:
            p = await new_project(pool, kind="narration")
            pid = str(p["id"])
            ok, errs = await race(6, lambda i: db.narration_uploaded(pool, pid, OWNER, f"k/take{i}.webm"))
            only(errs, Conflict)
            assert len(ok) == 1
            assert await pool.fetchval("select count(*) from editor_jobs where project_id = $1 and kind = 'generate'", pid) == 1
        finally:
            await pool.close()
    run(go())


# ------------------------------------------------------------------ structure stays valid

async def assert_chunks_dense(pool, pid):
    idx = [r["idx"] for r in await pool.fetch("select idx from chunks where project_id = $1 order by idx", pid)]
    assert idx == list(range(len(idx))), f"chunk order has gaps or duplicates: {idx}"


def test_simultaneous_splits_of_one_chunk():
    async def go():
        pool = await wide_pool()
        try:
            pid, cs = await editing_project(pool)
            await pool.execute("update chunks set text = 'one two three four five six' where id = $1", cs[0]["id"])
            ok, errs = await race(6, lambda i: db.split_chunk(pool, pid, OWNER, str(cs[0]["id"]), 1, 4 + i))
            only(errs, Conflict)
            assert len(ok) == 1
            await assert_chunks_dense(pool, pid)
            assert await pool.fetchval("select count(*) from chunks where project_id = $1", pid) == len(ROWS) + 1
        finally:
            await pool.close()
    run(go())


def test_finishing_audio_never_overwrites_a_newer_edit():
    async def go():
        pool = await wide_pool()
        try:
            for _ in range(15):                     # many rounds: the interleaving differs each time
                pid, cs = await editing_project(pool)
                cid = cs[0]["id"]
                await pool.execute("update chunks set revision = 1, status = 'generating', audio_key = null where id = $1", cid)

                async def make(i):
                    if i == 0:
                        return ("audio", await db.chunk_audio_ready(pool, cid, 1, "k/stale.wav", 1.0))
                    return ("edit", await db.edit_chunk(pool, pid, OWNER, str(cid), 1, {"text": "newer"}))
                _, errs = await race(2, make)
                only(errs, Conflict)
                row = await pool.fetchrow("select revision, status, audio_key, text from chunks where id = $1", cid)
                if row["revision"] == 2:            # the edit won: its new revision must not carry the stale audio as ready
                    assert row["status"] == "pending" and row["text"] == "newer"
                else:                               # audio landed first, then the edit was refused? impossible: edit takes rev 1
                    assert row["status"] == "ready" and row["audio_key"] == "k/stale.wav"
        finally:
            await pool.close()
    run(go())


def test_mixed_operations_keep_every_invariant():
    """8 tasks fire random edits, splits, merges, regenerations, voice changes and timeline saves."""
    async def go():
        pool = await wide_pool()
        try:
            pid, _ = await editing_project(pool)
            await db.get_timeline(pool, pid, OWNER, timeline.default_doc)
            rnd = random.Random(1234)

            async def actor(i):
                for _ in range(25):
                    rows = await db.list_chunks(pool, pid, OWNER)
                    if not rows:
                        return
                    c = rnd.choice(rows)
                    op = rnd.choice(["edit", "split", "merge", "regen", "voice", "timeline", "ready"])
                    try:
                        if op == "edit":
                            await db.edit_chunk(pool, pid, OWNER, str(c["id"]), c["revision"], {"text": f"t{i} {uuid.uuid4().hex[:4]} x"})
                        elif op == "split" and len(c["text"].split()) > 1:
                            await db.split_chunk(pool, pid, OWNER, str(c["id"]), c["revision"], c["text"].index(" ") + 1)
                        elif op == "merge":
                            nxt = next((r for r in rows if r["idx"] == c["idx"] + 1), None)
                            if nxt:
                                await db.merge_chunks(pool, pid, OWNER, str(c["id"]), c["revision"], str(nxt["id"]), nxt["revision"])
                        elif op == "regen":
                            await db.regenerate_chunk(pool, pid, OWNER, str(c["id"]))
                        elif op == "ready":
                            await db.chunk_audio_ready(pool, c["id"], c["revision"], f"k/{c['id']}.wav", 1.0)
                        elif op == "voice":
                            p = await db.get_project(pool, pid, OWNER)
                            await db.set_voice(pool, pid, OWNER, {"mode": "persona", "voice_id": f"v{i}"}, p["settings_version"])
                        elif op == "timeline":
                            tl = await db.get_timeline(pool, pid, OWNER, timeline.default_doc)

                            async def apply_fn(conn, doc):
                                d, _ = timeline.apply_all(doc, [{"type": "track.set", "track": "voice",
                                                                 "fields": {"gain_db": float(rnd.randint(-10, 0))}}], source_s=6.0)
                                return d, ["g"]
                            await db.save_timeline(pool, pid, OWNER, tl["version"], apply_fn, timeline.default_doc)
                    except (Conflict, NotFound, ValueError):
                        pass                        # expected losers of a race
            _, errs = await race(8, actor)
            only(errs)

            await assert_chunks_dense(pool, pid)
            # At most one live tts job per chunk, and it targets the chunk's current revision.
            bad = await pool.fetch(
                "select c.id, c.revision, array_agg(j.chunk_revision) revs from chunks c "
                "join editor_jobs j on j.chunk_id = c.id and j.kind = 'tts' and j.status = 'PENDING' "
                "where c.project_id = $1 group by c.id, c.revision "
                "having count(*) > 1 or bool_or(j.chunk_revision <> c.revision)", pid)
            assert not bad, f"duplicate or stale live jobs: {[dict(b) for b in bad]}"
            # A chunk marked ready always has audio.
            assert await pool.fetchval("select count(*) from chunks where project_id = $1 and status = 'ready' and audio_key is null", pid) == 0
            # Timeline version equals the number of accepted saves + 1.
            v = await pool.fetchval("select version from timelines where project_id = $1", pid)
            n = await pool.fetchval("select count(*) from timeline_ops where project_id = $1", pid)
            assert v == n + 1
        finally:
            await pool.close()
    run(go())


# ------------------------------------------------------------------ media service

def test_media_upload_completion_never_duplicates_processing_jobs():
    from media_service import db as mdb

    async def go():
        pool = await wide_pool()
        try:
            aid = str(uuid.uuid4())
            await mdb.create_asset(pool, OWNER, original_filename="v.mp4", storage_key=f"{OWNER}/{aid}/source.mp4",
                                   size_bytes=10, duration_ms=1000, asset_id=aid)
            ok, errs = await race(6, lambda i: mdb.complete_upload(pool, aid, OWNER, 10))
            only(errs, PermissionError)
            assert len(ok) >= 1
            kinds = sorted(r["kind"] for r in await pool.fetch("select kind from jobs where asset_id = $1", aid))
            assert kinds == ["probe", "proxy", "thumbnail"]
        finally:
            await pool.close()
    run(go())
