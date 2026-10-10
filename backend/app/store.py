"""Persistence.

Projects (job documents) live in Supabase `public.projects` when configured, otherwise in
local SQLite (tests, offline). Writes to Supabase are write-behind: the newest document per
project is kept in memory and flushed by one background thread at most every 0.5 s, so the
pipeline's frequent progress updates never block on the network.

The paid-API cache and voice-rate table always stay in local SQLite: they index files that
only exist on this machine."""

from __future__ import annotations

import copy
import json
import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from .config import DB_BACKEND, DB_PATH, STORAGE

log = logging.getLogger("vani.store")

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


# ---------------------------------------------------------------- projects: SQLite

def _sqlite_save(job: dict) -> None:
    with _lock:
        _conn.execute(
            "INSERT INTO jobs (id, created, data) VALUES (?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET data = excluded.data",
            (job["id"], job["created_at"] / 1000, json.dumps(job, ensure_ascii=False)),
        )
        _conn.commit()


def _sqlite_load(job_id: str) -> dict | None:
    with _lock:
        row = _conn.execute("SELECT data FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return json.loads(row[0]) if row else None


def _sqlite_list(user_id: str | None) -> list[dict]:
    with _lock:
        rows = _conn.execute("SELECT data FROM jobs ORDER BY created DESC").fetchall()
    jobs = [json.loads(r[0]) for r in rows]
    return [j for j in jobs if user_id is None or j.get("user_id") == user_id]


# ---------------------------------------------------------------- projects: Supabase

_mem: dict[str, dict] = {}          # newest document per project (read-through cache)
_dirty: dict[str, dict] = {}        # waiting to be flushed
_flush_cv = threading.Condition()


def _row(job: dict) -> dict:
    return {
        "id": job["id"], "user_id": job["user_id"], "upload_id": job.get("upload_id"),
        "name": job["name"], "mode": job["mode"], "status": job["status"],
        "src_lang": job.get("src_lang"), "tgt_lang": job.get("tgt_lang"),
        "duration_s": job.get("duration_s"), "data": job,
    }


def _flusher() -> None:
    from . import supa
    while True:
        with _flush_cv:
            while not _dirty:
                _flush_cv.wait()
            batch = list(_dirty.values())
            _dirty.clear()
        try:
            supa.admin().table("projects").upsert([_row(j) for j in batch]).execute()
        except Exception as e:
            log.error("project flush failed (%d docs), retrying: %s", len(batch), e)
            with _flush_cv:
                for j in batch:
                    _dirty.setdefault(j["id"], j)
            time.sleep(2)
            continue
        time.sleep(0.5)


def _supa_save(job: dict) -> None:
    doc = copy.deepcopy(job)
    with _flush_cv:
        _mem[job["id"]] = doc
        _dirty[job["id"]] = doc
        _flush_cv.notify()


def _supa_load(job_id: str) -> dict | None:
    if job_id in _mem:
        return copy.deepcopy(_mem[job_id])
    from . import supa
    r = supa.admin().table("projects").select("data").eq("id", job_id).limit(1).execute()
    if not r.data:
        return None
    doc = r.data[0]["data"]
    _mem[job_id] = doc
    return copy.deepcopy(doc)


def _supa_list(user_id: str | None) -> list[dict]:
    from . import supa
    q = supa.admin().table("projects").select("id, data").order("created_at", desc=True)
    if user_id is not None:
        q = q.eq("user_id", user_id)
    rows = q.execute().data
    # Prefer in-memory documents: they may be newer than the last flush.
    return [copy.deepcopy(_mem.get(r["id"], r["data"])) for r in rows]


def flush_now(timeout: float = 5.0) -> None:
    """Block until pending project writes are sent (used at shutdown)."""
    t0 = time.time()
    while _dirty and time.time() - t0 < timeout:
        time.sleep(0.1)


if DB_BACKEND == "supabase":
    threading.Thread(target=_flusher, name="projects-flusher", daemon=True).start()
    save_job, load_job, _list = _supa_save, _supa_load, _supa_list
else:
    save_job, load_job, _list = _sqlite_save, _sqlite_load, _sqlite_list


def list_jobs(user_id: str | None = None) -> list[dict]:
    """All projects (user_id=None, used for resuming work at startup) or one user's."""
    return _list(user_id)


def record_upload(user_id: str, kind: str, filename: str, size: int, duration: float | None, path: str) -> str | None:
    """Insert an `uploads` row; returns its id (None when running on SQLite)."""
    if DB_BACKEND != "supabase":
        return None
    from . import supa
    r = supa.admin().table("uploads").insert({
        "user_id": user_id, "kind": kind, "filename": filename[:255], "size_bytes": size,
        "duration_s": duration, "storage_path": path,
    }).execute()
    return r.data[0]["id"]


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
