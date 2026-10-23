"""Fair-share rate limiting for the shared provider keys (one Gnani key, one Gemini key, used by
every user).

Each provider has a per-minute budget (config). A call is allowed when
  * the whole app has made fewer than BUDGET calls to that provider in the last 60 s, and
  * this user has made fewer than their fair share: ceil(BUDGET / active users), where active
    users = distinct owners with editor jobs queued or running right now.
So one active user can use the whole budget, five active users get a fifth each, and the share
is recomputed on every call as people start and finish work.

The check and the recording happen in one transaction under a per-provider advisory lock, so
parallel workers (in any number of processes) can never overshoot the budget together.
A refused call raises Throttled with how long to wait; the worker puts the job back in the
queue for then, without counting it as a failed attempt.
"""

from __future__ import annotations

import math

import asyncpg

from .config import RATE_LIMITS

WINDOW_S = 60


class Throttled(Exception):
    """The provider budget (global or this user's share) is used up for now."""

    def __init__(self, provider: str, delay_s: float, reason: str):
        super().__init__(f"{provider} rate limited ({reason}); retry in {delay_s:.0f}s")
        self.provider, self.delay_s, self.reason = provider, delay_s, reason


async def active_users(conn) -> int:
    return await conn.fetchval(
        "select count(distinct owner_id) from editor_jobs where status in ('PENDING', 'RUNNING') "
        "and kind in ('generate', 'tts')"
    ) or 0


def fair_share(budget: int, active: int) -> int:
    return max(1, math.ceil(budget / max(1, active)))


async def acquire(pool: asyncpg.Pool, provider: str, owner_id: str) -> None:
    """Record one call, or raise Throttled. No-op for providers without a configured budget."""
    budget = RATE_LIMITS.get(provider)
    if not budget:
        return
    async with pool.acquire() as conn, conn.transaction():
        await conn.execute("select pg_advisory_xact_lock(hashtext($1))", f"ratelimit:{provider}")
        await conn.execute(
            "delete from provider_calls where provider = $1 and at < now() - make_interval(secs => $2)",
            provider, WINDOW_S,
        )
        row = await conn.fetchrow(
            "select count(*) as total, count(*) filter (where owner_id = $2) as mine, "
            "  min(at) as oldest, min(at) filter (where owner_id = $2) as my_oldest "
            "from provider_calls where provider = $1",
            provider, owner_id,
        )
        if row["total"] >= budget:
            raise Throttled(provider, await _wait(conn, row["oldest"]), "app-wide budget used")
        share = fair_share(budget, await active_users(conn))
        if row["mine"] >= share:
            raise Throttled(provider, await _wait(conn, row["my_oldest"]), f"fair share {share}/min used")
        await conn.execute("insert into provider_calls (provider, owner_id) values ($1, $2)", provider, owner_id)


async def _wait(conn, oldest) -> float:
    """Seconds until the oldest counted call leaves the window (at least 1 s)."""
    if oldest is None:
        return 1.0
    left = await conn.fetchval("select extract(epoch from ($1::timestamptz + make_interval(secs => $2) - now()))",
                               oldest, WINDOW_S)
    return max(1.0, float(left or 1.0))
