"""SQLite persistence. Jobs are stored as one JSON document each (they're small and
always read whole); the cache maps content hashes of paid API calls to results."""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .config import DB_PATH, STORAGE

_lock = threading.Lock()
_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.execute("PRAGMA journal_mode=WAL")
_conn.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, created REAL, data TEXT)")
_conn.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, kind TEXT, value TEXT, created REAL)")
_conn.execute("CREATE TABLE IF NOT EXISTS voice_rate (voice TEXT, lang TEXT, cps REAL, n INTEGER, PRIMARY KEY (voice, lang))")
_conn.commit()


def job_dir(job_id: str) -> Path:
    d = STORAGE / "jobs" / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_job(job: dict) -> None:
    with _lock:
        _conn.execute(
            "INSERT INTO jobs (id, created, data) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
            (job["id"], job["created_at"] / 1000, json.dumps(job, ensure_ascii=False)),
        )
        _conn.commit()


def load_job(job_id: str) -> dict | None:
    with _lock:
        row = _conn.execute("SELECT data FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return json.loads(row[0]) if row else None


def list_jobs() -> list[dict]:
    with _lock:
        rows = _conn.execute("SELECT data FROM jobs ORDER BY created DESC").fetchall()
    return [json.loads(r[0]) for r in rows]


def cache_get(key: str) -> Any | None:
    with _lock:
        row = _conn.execute("SELECT value FROM cache WHERE key = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def cache_put(key: str, kind: str, value: Any) -> None:
    with _lock:
        _conn.execute(
            "INSERT OR REPLACE INTO cache (key, kind, value, created) VALUES (?, ?, ?, ?)",
            (key, kind, json.dumps(value, ensure_ascii=False), time.time()),
        )
        _conn.commit()


def voice_cps(voice: str, lang: str) -> float | None:
    with _lock:
        row = _conn.execute("SELECT cps FROM voice_rate WHERE voice = ? AND lang = ?", (voice, lang)).fetchone()
    return row[0] if row else None


def record_voice_cps(voice: str, lang: str, cps: float) -> None:
    """Running mean of a voice's characters per second, learnt from real TTS output
    instead of spending calls on calibration."""
    with _lock:
        row = _conn.execute("SELECT cps, n FROM voice_rate WHERE voice = ? AND lang = ?", (voice, lang)).fetchone()
        if row:
            mean, n = row
            n2 = min(n + 1, 50)
            _conn.execute("UPDATE voice_rate SET cps = ?, n = ? WHERE voice = ? AND lang = ?",
                          (mean + (cps - mean) / n2, n2, voice, lang))
        else:
            _conn.execute("INSERT INTO voice_rate (voice, lang, cps, n) VALUES (?, ?, ?, 1)", (voice, lang, cps))
        _conn.commit()
