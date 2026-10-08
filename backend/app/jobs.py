"""Job state, live events (for SSE) and a single background worker."""

from __future__ import annotations

import asyncio
import copy
import logging
import traceback
from typing import Awaitable, Callable

from . import store

log = logging.getLogger("vani.jobs")

_subscribers: dict[str, set[asyncio.Queue]] = {}
_queue: asyncio.Queue | None = None


def public(job: dict) -> dict:
    """What the frontend sees: everything except internal bookkeeping under '_'."""
    return {k: copy.deepcopy(v) for k, v in job.items() if not k.startswith("_")}


def update(job: dict, **fields) -> dict:
    job.update(fields)
    store.save_job(job)
    data = public(job)
    for q in list(_subscribers.get(job["id"], ())):
        if q.full():
            try:
                q.get_nowait()
            except asyncio.QueueEmpty:
                pass
        q.put_nowait(data)
    return job


def subscribe(job_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _subscribers.setdefault(job_id, set()).add(q)
    return q


def unsubscribe(job_id: str, q: asyncio.Queue) -> None:
    _subscribers.get(job_id, set()).discard(q)


def enqueue(fn: Callable[[str], Awaitable[None]], job_id: str) -> None:
    assert _queue is not None, "worker not started"
    _queue.put_nowait((fn, job_id))


async def worker() -> None:
    """One job at a time keeps Gnani rate limits and the credit budget predictable."""
    global _queue
    _queue = asyncio.Queue()
    while True:
        fn, job_id = await _queue.get()
        try:
            await fn(job_id)
        except Exception as e:   # a failed job must not kill the worker
            log.error("job %s failed: %s\n%s", job_id, e, traceback.format_exc())
            job = store.load_job(job_id)
            if job:
                update(job, status="failed", stage=None, error=friendly(e))
        finally:
            _queue.task_done()


def friendly(e: Exception) -> str:
    msg = str(e)
    if "GNANI_API_KEY" in msg or "GOOGLE_API_KEY" in msg:
        return msg
    if "429" in msg:
        return "The speech service is busy (rate limited). Try again in a minute."
    if "401" in msg or "403" in msg:
        return "The speech service rejected the API key, or the credits have run out."
    return f"Processing failed: {msg[:240]}"
