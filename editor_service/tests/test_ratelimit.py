"""Fair-share rate limiting and per-user limits, against a real Postgres (DATABASE_URL_TEST)."""

import asyncio
import uuid

import asyncpg
import pytest

from editor_service import db, ratelimit, routes
from editor_service.errors import LimitReached
from editor_service.tests.test_db import OTHER, OWNER, URL, fresh_pool, new_project

pytestmark = pytest.mark.skipif(not URL, reason="DATABASE_URL_TEST not set")

THIRD = "00000000-0000-0000-0000-000000000003"


def run(coro):
    return asyncio.run(coro)


async def setup(owners):
    """Fresh schema; each owner gets one project with one pending job (= an active user)."""
    p = await fresh_pool()
    await p.execute("insert into auth.users values ($1) on conflict do nothing", THIRD)
    await p.execute("insert into public.users (id, username, first_name, last_name, email) values "
                    "($1, 'third', 'T', 'H', 'h@example.com') on conflict do nothing", THIRD)
    for o in owners:
        await new_project(p, owner=o)            # script project → one PENDING generate job
    await p.close()
    return await asyncpg.create_pool(URL, min_size=8, max_size=16)


def test_fair_share_formula():
    assert ratelimit.fair_share(60, 0) == 60
    assert ratelimit.fair_share(60, 1) == 60
    assert ratelimit.fair_share(60, 4) == 15
    assert ratelimit.fair_share(4, 3) == 2            # rounds up: nobody gets 0
    assert ratelimit.fair_share(4, 100) == 1


def test_budget_is_split_between_active_users(monkeypatch):
    monkeypatch.setitem(ratelimit.RATE_LIMITS, "gnani_tts", 6)

    async def go():
        pool = await setup([OWNER, OTHER, THIRD])
        try:
            for o in (OWNER, OTHER, THIRD):
                await ratelimit.acquire(pool, "gnani_tts", o)
                await ratelimit.acquire(pool, "gnani_tts", o)
            with pytest.raises(ratelimit.Throttled) as e:      # app-wide budget of 6 used
                await ratelimit.acquire(pool, "gnani_tts", OWNER)
            assert "app-wide" in e.value.reason and 1 <= e.value.delay_s <= 60
        finally:
            await pool.close()
    run(go())


def test_one_user_cannot_take_more_than_their_share(monkeypatch):
    monkeypatch.setitem(ratelimit.RATE_LIMITS, "gnani_tts", 6)

    async def go():
        pool = await setup([OWNER, OTHER, THIRD])
        try:
            await ratelimit.acquire(pool, "gnani_tts", OWNER)
            await ratelimit.acquire(pool, "gnani_tts", OWNER)
            with pytest.raises(ratelimit.Throttled) as e:      # 6 / 3 active = 2 each
                await ratelimit.acquire(pool, "gnani_tts", OWNER)
            assert "fair share 2/min" in e.value.reason
            await ratelimit.acquire(pool, "gnani_tts", OTHER)  # others are unaffected
        finally:
            await pool.close()
    run(go())


def test_share_grows_when_others_finish(monkeypatch):
    monkeypatch.setitem(ratelimit.RATE_LIMITS, "gnani_tts", 6)

    async def go():
        pool = await setup([OWNER, OTHER, THIRD])
        try:
            await pool.execute("update editor_jobs set status = 'DONE' where owner_id <> $1", OWNER)
            for _ in range(6):                                 # alone now: the whole budget
                await ratelimit.acquire(pool, "gnani_tts", OWNER)
            with pytest.raises(ratelimit.Throttled):
                await ratelimit.acquire(pool, "gnani_tts", OWNER)
        finally:
            await pool.close()
    run(go())


def test_parallel_workers_never_overshoot_the_budget(monkeypatch):
    monkeypatch.setitem(ratelimit.RATE_LIMITS, "gnani_tts", 10)

    async def go():
        pool = await setup([OWNER])
        try:
            gate = asyncio.Event()

            async def one():
                await gate.wait()
                try:
                    await ratelimit.acquire(pool, "gnani_tts", OWNER)
                    return True
                except ratelimit.Throttled:
                    return False
            tasks = [asyncio.create_task(one()) for _ in range(30)]
            await asyncio.sleep(0.05); gate.set()
            ok = sum(await asyncio.gather(*tasks))
            assert ok == 10
            assert await pool.fetchval("select count(*) from provider_calls where provider = 'gnani_tts'") == 10
        finally:
            await pool.close()
    run(go())


def test_providers_without_a_budget_are_not_limited(monkeypatch):
    monkeypatch.setitem(ratelimit.RATE_LIMITS, "gemini", 0)

    async def go():
        pool = await setup([OWNER])
        try:
            for _ in range(50):
                await ratelimit.acquire(pool, "gemini", OWNER)
        finally:
            await pool.close()
    run(go())


def test_deferred_job_keeps_its_attempts():
    async def go():
        pool = await setup([OWNER])
        try:
            job = await db.claim_job(pool)
            assert job["attempts"] == 1
            await db.defer_job(pool, job, 30, "gnani_tts rate limited")
            row = await pool.fetchrow("select status, attempts, run_after > now() + interval '25 seconds' as later "
                                      "from editor_jobs where id = $1", job["id"])
            assert (row["status"], row["attempts"], row["later"]) == ("PENDING", 0, True)
            assert await db.claim_job(pool) is None             # not due yet
        finally:
            await pool.close()
    run(go())


def test_claiming_is_fair_between_users():
    async def go():
        pool = await setup([OWNER, OTHER])
        try:
            busy = (await db.get_project(pool, *(await pool.fetchrow(
                "select id, owner_id from editor_projects where owner_id = $1", OWNER)).values()))["id"]
            await pool.executemany("insert into editor_jobs (project_id, owner_id, kind) values ($1, $2, 'generate')",
                                   [(busy, OWNER)] * 20)
            first = await db.claim_job(pool)                    # oldest overall
            nxt = await db.claim_job(pool)                      # OWNER already has one running → OTHER goes next
            assert {first["owner_id"], nxt["owner_id"]} == {uuid.UUID(OWNER), uuid.UUID(OTHER)}
        finally:
            await pool.close()
    run(go())


def test_generation_cap_steps_down_as_the_app_gets_busy(monkeypatch):
    monkeypatch.setattr(routes, "MAX_ACTIVE_GENERATIONS", 3)
    monkeypatch.setattr(routes, "BUSY_ACTIVE_USERS", 10)
    caps = [routes.generation_cap(n) for n in (0, 1, 2, 5, 9, 10, 50)]
    assert caps == sorted(caps, reverse=True) and caps[0] == 3 and caps[-1] == 1 and caps[-2] == 1


def test_per_user_limits(monkeypatch):
    async def go():
        pool = await setup([OWNER])
        try:
            monkeypatch.setattr(routes, "MAX_PROJECTS_PER_USER", 1)
            with pytest.raises(LimitReached, match="1 projects"):
                await routes.check_user_limits(pool, OWNER, new_project=True)
            monkeypatch.setattr(routes, "MAX_PROJECTS_PER_USER", 50)
            monkeypatch.setattr(routes, "MAX_ACTIVE_GENERATIONS", 1)
            with pytest.raises(LimitReached, match="generating"):  # the project from setup is generating
                await routes.check_user_limits(pool, OWNER, new_project=True)
            await routes.check_user_limits(pool, OTHER, new_project=True)   # someone else is fine
        finally:
            await pool.close()
    run(go())
