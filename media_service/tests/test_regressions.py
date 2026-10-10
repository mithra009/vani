"""Regression tests for production bugs found 2026-10-10.

1. storage.upload_file swapped arguments — supabase-py is upload(key, payload, opts),
   so the client tried to read the storage key as a local file (FileNotFoundError
   on every thumbnail/proxy upload).
2. db.finish_job bound a raw dict into the assets.metadata jsonb column — asyncpg
   needs a JSON string (DataError on every probe finish).
3. Windows lock race — Defender briefly locks a freshly-written derivative
   (WinError 32); upload_file now reads bytes with a retry, and the worker's
   tempdir cleanup ignores such errors.
"""

import asyncio
import json

import pytest

from media_service import db, storage


class TestUploadFilePayload:
    def test_uploads_bytes_key_first(self, monkeypatch, tmp_path):
        """upload(key, bytes, opts) — never a path, never the key as a file."""
        local = tmp_path / "thumb.jpg"
        local.write_bytes(b"jpegbytes")
        calls = {}

        class FakeBucket:
            def upload(self, key, payload, options):
                calls.update(key=key, payload=payload, options=options)

        class FakeStorage:
            def from_(self, bucket):
                calls["bucket"] = bucket
                return FakeBucket()

        class FakeClient:
            storage = FakeStorage()

        monkeypatch.setattr(storage, "admin", lambda: FakeClient())
        storage.upload_file(str(local), "owner/asset/thumb.jpg", "image/jpeg")
        assert calls["key"] == "owner/asset/thumb.jpg"
        assert calls["payload"] == b"jpegbytes"           # bytes, not a path
        assert calls["options"]["content-type"] == "image/jpeg"
        # storage3 copies option values straight into HTTP headers; httpx rejects
        # non-str/bytes (a bool "upsert": True crashed every derivative upload).
        for k, v in calls["options"].items():
            assert isinstance(v, str), f"option {k!r} must be a string, got {type(v)}"

    def test_retries_locked_file_then_succeeds(self, monkeypatch, tmp_path):
        """WinError 32: first open hits a sharing violation, second succeeds."""
        local = tmp_path / "proxy.mp4"
        local.write_bytes(b"mp4bytes")
        attempts = {"n": 0}
        real_open = open

        def flaky_open(path, mode="r", *a, **kw):
            if str(path) == str(local) and "b" in mode and attempts["n"] == 0:
                attempts["n"] += 1
                raise PermissionError(13, "being used by another process", str(path))
            return real_open(path, mode, *a, **kw)

        monkeypatch.setattr("builtins.open", flaky_open)
        data = storage._read_with_retry(str(local), tries=3, delay=0)
        assert data == b"mp4bytes"
        assert attempts["n"] == 1

    def test_raises_after_exhausting_retries(self, monkeypatch, tmp_path):
        local = tmp_path / "gone.mp4"

        def always_locked(path, mode="r", *a, **kw):
            raise PermissionError(13, "being used by another process", str(path))

        monkeypatch.setattr("builtins.open", always_locked)
        with pytest.raises(PermissionError):
            storage._read_with_retry(str(local), tries=2, delay=0)


class _FakeConn:
    def __init__(self, row):
        self._row = row
        self.fetches = []

    def transaction(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def execute(self, sql, *args):
        return "UPDATE 1"

    async def fetchrow(self, sql, *args):
        self.fetches.append((sql, args))
        return self._row


class _FakePool:
    def __init__(self, conn):
        self._conn = conn

    def acquire(self):
        return self._conn


class TestFinishJobJsonb:
    def test_dict_values_are_json_serialized(self):
        row = {"id": "a", "metadata_status": "READY", "thumbnail_status": "PENDING",
               "proxy_status": "PENDING", "status": "PROCESSING"}
        conn = _FakeConn(row)
        job = {"id": "j", "asset_id": "a", "kind": "probe", "attempts": 1}
        asyncio.run(db.finish_job(
            _FakePool(conn), job, ok=True,
            asset_values={"duration_ms": 1000, "metadata": {"has_video": True, "fps": 25.0}},
        ))
        # the assets UPDATE is the fetchrow that carries metadata
        _, args = conn.fetches[0]
        # args = (asset_id, duration_ms, metadata_json, metadata_status)
        meta_args = [a for a in args if isinstance(a, str) and a.startswith("{")]
        assert meta_args, f"metadata was not JSON-serialized: {args!r}"
        assert json.loads(meta_args[0]) == {"has_video": True, "fps": 25.0}
