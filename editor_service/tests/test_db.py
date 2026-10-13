"""db.py against a real Postgres: the real migrations (001, 002, 004…) on a stub `auth` schema.

Runs only with DATABASE_URL_TEST pointing at a throwaway database (it is wiped):
    DATABASE_URL_TEST=postgresql://postgres@localhost:5432/vani_test pytest editor_service/tests/test_db.py
"""

import asyncio
import os
import uuid
from pathlib import Path

import pytest

URL = os.environ.get("DATABASE_URL_TEST", "")
pytestmark = pytest.mark.skipif(not URL, reason="DATABASE_URL_TEST not set")

MIGRATIONS = Path(__file__).resolve().parents[2] / "supabase" / "migrations"
OWNER = "00000000-0000-0000-0000-000000000001"
OTHER = "00000000-0000-0000-0000-000000000002"

STUB = """
drop schema if exists public cascade; create schema public;
drop schema if exists auth cascade; create schema auth;
create table auth.users (id uuid primary key);
create function auth.uid() returns uuid language sql stable as $$ select null::uuid $$;
drop schema if exists storage cascade; create schema storage;
create table storage.buckets (id text primary key, name text, public boolean,
  file_size_limit bigint, allowed_mime_types text[]);
create table storage.objects (id uuid primary key default gen_random_uuid(), bucket_id text, name text);
create function storage.foldername(name text) returns text[] language sql immutable
  as $$ select string_to_array(name, '/') $$;
drop publication if exists supabase_realtime; create publication supabase_realtime;
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then create role authenticated; end if;
  if not exists (select 1 from pg_roles where rolname = 'anon') then create role anon; end if;
end $$;
"""


def run(coro):
    return asyncio.run(coro)


async def fresh_pool():
    import asyncpg
    conn = await asyncpg.connect(URL)
    try:
        await conn.execute(STUB)
        for f in sorted(MIGRATIONS.glob("*.sql")):
            await conn.execute(f.read_text(encoding="utf-8"))
        await conn.execute("insert into auth.users values ($1), ($2)", OWNER, OTHER)
        await conn.execute(
            "insert into public.users (id, username, first_name, last_name, email) values "
            "($1, 'owner', 'O', 'W', 'o@example.com'), ($2, 'other', 'O', 'T', 't@example.com')", OWNER, OTHER)
    finally:
        await conn.close()
    return await asyncpg.create_pool(URL, min_size=1, max_size=4)


async def ready_asset(pool, owner=OWNER):
    aid = str(uuid.uuid4())
    await pool.execute(
        "insert into assets (id, owner_id, original_filename, storage_key, status, duration_ms) "
        "values ($1, $2, 'v.mp4', $3, 'READY', 6000)", aid, owner, f"{owner}/{aid}/source.mp4")
    return aid


VOICE = {"mode": "persona", "voice_id": "anu"}


async def new_project(pool, kind="script", owner=OWNER):
    from editor_service import db
    aid = await ready_asset(pool, owner)
    return await db.create_project(
        pool, owner, asset_id=aid, name="P", input_kind=kind,
        script_text="Hello. World." if kind == "script" else None,
        src_lang="hi-IN", tgt_lang="hi-IN", voice=VOICE, duration_s=6.0)


ROWS = [
    {"idx": 0, "source_text": "Hello.", "char_start": 0, "char_end": 6, "text": "Hello.",
     "anchor_src_s": 0.0, "anchor_len_s": 0.5, "overflow": False, "emotion_tag": "neutral"},
    {"idx": 1, "source_text": "World.", "char_start": 7, "char_end": 13, "text": "World.",
     "anchor_src_s": 0.8, "anchor_len_s": 0.5, "overflow": False, "emotion_tag": "laugh"},
]


def test_generate_lifecycle_and_stale_guard():
    from editor_service import db
    from editor_service.errors import Conflict, NotFound

    async def go():
        pool = await fresh_pool()
        try:
            p = await new_project(pool)
            pid = str(p["id"])
            assert p["status"] == "generating"
            job = await db.claim_job(pool)
            assert job["kind"] == "generate" and job["attempts"] == 1
            assert await db.claim_job(pool) is None                     # SKIP LOCKED / RUNNING

            chunks = await db.replace_chunks(pool, pid, OWNER, ROWS, 6.0)
            await db.finish_job(pool, job, outcome="DONE")
            tts = [await db.claim_job(pool), await db.claim_job(pool)]
            assert {t["kind"] for t in tts} == {"tts"}

            c0, c1 = chunks
            assert (await db.chunk_generating(pool, c0["id"], 1))["status"] == "generating"
            # The user edits c0 while its audio renders → the old result must not land.
            edited = await db.edit_chunk(pool, pid, OWNER, str(c0["id"]), 1, {"text": "Hi."})
            assert edited["revision"] == 2 and edited["status"] == "pending"
            assert await db.chunk_audio_ready(pool, c0["id"], 1, "k/old.wav", 1.0) is False
            with pytest.raises(Conflict):
                await db.edit_chunk(pool, pid, OWNER, str(c0["id"]), 1, {"text": "again"})
            with pytest.raises(NotFound):
                await db.edit_chunk(pool, pid, OTHER, str(c0["id"]), 2, {"text": "x"})

            assert await db.chunk_audio_ready(pool, c1["id"], 1, "k/c1.wav", 1.0) is True
            assert (await db.get_project(pool, pid, OWNER))["status"] == "generating"   # c0 still pending
            new = await db.claim_job(pool)
            assert new["chunk_id"] == c0["id"] and new["chunk_revision"] == 2
            assert await db.chunk_audio_ready(pool, c0["id"], 2, "k/c0.wav", 1.0) is True
            assert (await db.get_project(pool, pid, OWNER))["status"] == "editing"
        finally:
            await pool.close()
    run(go())


def test_failures_are_final_and_visible():
    from editor_service import db

    async def go():
        pool = await fresh_pool()
        try:
            p = await new_project(pool)
            job = await db.claim_job(pool)
            final = await db.finish_job(pool, job, outcome="FAILED", code="provider_unavailable", error="503", retry=True)
            assert final is False
            row = await pool.fetchrow("select status, run_after > now() as later from editor_jobs where id = $1", job["id"])
            assert row["status"] == "FAILED" and row["later"]
            final = await db.finish_job(pool, job, outcome="FAILED", code="chunking_invalid", error="bad", retry=False)
            assert final is True
            await pool.execute("update editor_jobs set run_after = now()")
            assert await db.claim_job(pool) is None                       # never re-claimed
            await db.fail_project(pool, str(p["id"]), "chunking_invalid", "bad")
            got = await db.get_project(pool, str(p["id"]), OWNER)
            assert (got["status"], got["error_code"]) == ("failed", "chunking_invalid")
            retried = await db.retry_generate(pool, str(p["id"]), OWNER)
            assert retried["status"] == "generating" and retried["error_code"] is None
            assert (await db.claim_job(pool))["kind"] == "generate"
        finally:
            await pool.close()
    run(go())


def test_voice_change_regenerates_all_and_is_version_checked():
    from editor_service import db
    from editor_service.errors import Conflict

    async def go():
        pool = await fresh_pool()
        try:
            p = await new_project(pool)
            pid = str(p["id"])
            await db.finish_job(pool, await db.claim_job(pool), outcome="DONE")
            cs = await db.replace_chunks(pool, pid, OWNER, ROWS, 6.0)
            for c in cs:
                await db.chunk_audio_ready(pool, c["id"], 1, f"k/{c['idx']}.wav", 1.0)
            await pool.execute("update editor_jobs set status = 'DONE'")
            assert (await db.get_project(pool, pid, OWNER))["status"] == "editing"
            p2 = await db.set_voice(pool, pid, OWNER, {"mode": "persona", "voice_id": "ravi"}, 1)
            assert p2["status"] == "generating" and p2["settings_version"] == 2
            assert {c["status"] for c in await db.list_chunks(pool, pid, OWNER)} == {"pending"}
            jobs = await pool.fetch("select chunk_revision from editor_jobs where status = 'PENDING'")
            assert sorted(j["chunk_revision"] for j in jobs) == [2, 2]
            with pytest.raises(Conflict):
                await db.set_voice(pool, pid, OWNER, VOICE, 1)
        finally:
            await pool.close()
    run(go())


def test_narration_is_one_take():
    from editor_service import db
    from editor_service.errors import Conflict

    async def go():
        pool = await fresh_pool()
        try:
            p = await new_project(pool, kind="narration")
            assert p["status"] == "awaiting_narration"
            assert await db.claim_job(pool) is None
            pid = str(p["id"])
            got = await db.narration_uploaded(pool, pid, OWNER, f"{OWNER}/projects/{pid}/narration.webm")
            assert got["status"] == "generating"
            with pytest.raises(Conflict):
                await db.narration_uploaded(pool, pid, OWNER, "x")
        finally:
            await pool.close()
    run(go())


async def editing_project(pool):
    from editor_service import db
    p = await new_project(pool)
    pid = str(p["id"])
    await db.finish_job(pool, await db.claim_job(pool), outcome="DONE")
    cs = await db.replace_chunks(pool, pid, OWNER, ROWS, 6.0)
    for c in cs:
        await db.chunk_audio_ready(pool, c["id"], 1, f"k/{c['idx']}.wav", 1.0)
    await pool.execute("update editor_jobs set status = 'DONE'")
    return pid, cs


def test_timeline_versioning_and_conflict():
    from editor_service import db, timeline

    async def go():
        pool = await fresh_pool()
        try:
            pid, cs = await editing_project(pool)
            tl0 = await db.get_timeline(pool, pid, OWNER, timeline.default_doc)
            assert tl0["version"] == 1 and tl0["doc"]["video"][0]["src_out"] == 6.0

            async def cut(conn, doc):
                d, _ = timeline.apply_all(doc, [{"type": "video.split", "clip_id": "vc0", "at_src": 3.0, "new_id": "b"}],
                                          source_s=6.0)
                return d, ["split"]
            saved = await db.save_timeline(pool, pid, OWNER, 1, cut, timeline.default_doc)
            assert saved["version"] == 2 and len(saved["doc"]["video"]) == 2
            with pytest.raises(db.VersionConflict) as e:
                await db.save_timeline(pool, pid, OWNER, 1, cut, timeline.default_doc)
            assert e.value.current["version"] == 2
            assert await pool.fetchval("select count(*) from timeline_ops where project_id = $1", pid) == 1

            async def bad(conn, doc):
                raise ValueError("nope")
            with pytest.raises(ValueError):
                await db.save_timeline(pool, pid, OWNER, 2, bad, timeline.default_doc)
            assert (await db.get_timeline(pool, pid, OWNER, timeline.default_doc))["version"] == 2   # rolled back
        finally:
            await pool.close()
    run(go())


def test_split_and_merge_keep_order_and_regenerate():
    from editor_service import db
    from editor_service.errors import Conflict

    async def go():
        pool = await fresh_pool()
        try:
            pid, cs = await editing_project(pool)
            await pool.execute("update chunks set text = 'Hello there friend.' where id = $1", cs[0]["id"])
            a, b = await db.split_chunk(pool, pid, OWNER, str(cs[0]["id"]), 1, 12)
            assert (a["text"], b["text"]) == ("Hello there", "friend.")
            rows = await db.list_chunks(pool, pid, OWNER)
            assert [r["idx"] for r in rows] == [0, 1, 2]
            assert [r["text"] for r in rows] == ["Hello there", "friend.", "World."]
            assert rows[0]["char_end"] == rows[1]["char_start"]
            assert float(rows[1]["anchor_src_s"]) > float(rows[0]["anchor_src_s"])
            assert (await db.get_project(pool, pid, OWNER))["status"] == "generating"
            assert await pool.fetchval("select count(*) from editor_jobs where status = 'PENDING' and kind = 'tts'") == 2
            with pytest.raises(Conflict):
                await db.split_chunk(pool, pid, OWNER, str(a["id"]), 1, 3)
            with pytest.raises(ValueError):
                await db.split_chunk(pool, pid, OWNER, str(a["id"]), a["revision"], 0)

            m = await db.merge_chunks(pool, pid, OWNER, str(rows[1]["id"]), rows[1]["revision"],
                                      str(rows[2]["id"]), rows[2]["revision"])
            assert m["text"] == "friend. World." and m["status"] == "pending"
            rows = await db.list_chunks(pool, pid, OWNER)
            assert [r["idx"] for r in rows] == [0, 1] and len(rows) == 2
            with pytest.raises(ValueError):
                await db.merge_chunks(pool, pid, OWNER, str(rows[1]["id"]), rows[1]["revision"],
                                      str(rows[0]["id"]), rows[0]["revision"])
        finally:
            await pool.close()
    run(go())
