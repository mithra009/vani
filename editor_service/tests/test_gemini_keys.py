"""GeminiLanguage over several keys, with stand-in clients (no network): rotation, 429 failover and the
per-key quotas. The fake providers never reach this code, so it needs its own test."""

import asyncio

import pytest
from google.genai import errors as gerrors

from editor_service import providers as p


class _Resp:
    text = '[{"id": 0, "text": "ok"}]'


def _client(log, i, fail):
    class Models:
        async def generate_content(self, **kw):
            log.append(i)
            if fail[i]:
                raise gerrors.APIError(429, {"error": {"code": 429, "message": "quota", "status": "RESOURCE_EXHAUSTED"}})
            return _Resp()

    class Aio:
        models = Models()

    class C:
        aio = Aio()
    return C()


def _gemini(n, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(p.time, "monotonic", lambda: clock[0])
    real_sleep = asyncio.sleep

    async def fake_sleep(s):
        clock[0] += s
        await real_sleep(0)
    monkeypatch.setattr(p.asyncio, "sleep", fake_sleep)
    g = p.GeminiLanguage.__new__(p.GeminiLanguage)
    log, fail = [], [False] * n
    g.clients = [_client(log, i, fail) for i in range(n)]
    g.quota = [p._KeyQuota() for _ in range(n)]
    g.next, g.lock = 0, asyncio.Lock()
    return g, log, fail, clock


ITEMS = [{"id": 0, "text": "x"}]


def test_calls_rotate_and_a_429_moves_the_call_to_the_next_key(monkeypatch):
    g, log, fail, _ = _gemini(3, monkeypatch)

    async def go():
        for _ in range(3):
            await g.translate(ITEMS, "en-IN", "kn-IN")
        assert log == [0, 1, 2]
        log.clear()
        fail[0] = True
        await g.translate(ITEMS, "en-IN", "kn-IN")
        assert log == [0, 1] and g.quota[0].rest_until > 0          # key 1 rests, key 2 answered
        fail[1] = fail[2] = True
        with pytest.raises(p.ProviderError):
            await g.translate(ITEMS, "en-IN", "kn-IN")
    asyncio.run(go())


def test_each_key_is_held_to_its_own_per_minute_and_per_day_limits(monkeypatch):
    g, log, _, clock = _gemini(2, monkeypatch)

    async def go():
        n = p.GEMINI_KEY_RPM * 2
        for _ in range(n + 1):
            await g.translate(ITEMS, "en-IN", "kn-IN")
        assert [log.count(0), log.count(1)] == [p.GEMINI_KEY_RPM + 1, p.GEMINI_KEY_RPM]
        assert clock[0] - 1000 == pytest.approx(60)                   # call n+1 waited for a free slot
    asyncio.run(go())

    g, log, _, _ = _gemini(1, monkeypatch)
    monkeypatch.setattr(p, "GEMINI_KEY_RPM", 10_000)

    async def day():
        for _ in range(p.GEMINI_KEY_RPD):
            await g.translate(ITEMS, "en-IN", "kn-IN")
        with pytest.raises(p.ProviderError):                         # the day is used up: fail, don't wait
            await g.translate(ITEMS, "en-IN", "kn-IN")
    asyncio.run(day())
