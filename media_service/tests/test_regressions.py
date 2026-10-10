"""Regression tests for two production bugs found 2026-10-10.

1. storage.upload_file swapped arguments — supabase-py is upload(key, path, opts),
   so the client tried to read the storage key as a local file (FileNotFoundError
   on every thumbnail/proxy upload).
2. db.finish_job bound a raw dict into the assets.metadata jsonb column — asyncpg
   needs a JSON string (DataError on every probe finish).
"""

import asyncio
import json

from media_service import db, storage


class TestUploadFileArgumentOrder:
    def test_key_first_then_local_path(self, monkeypatch):
        calls = {}

        class FakeBucket:
            def upload(self, key, path, options):
                calls.update(key=key, path=path, options=options)

        class FakeStorage:
            def from_(self, bucket):
                calls["bucket"] = bucket
                return FakeBucket()

        class FakeClient:
            storage = FakeStorage()

        monkeypatch.setattr(storage, "admin", lambda: FakeClient())
        storage.upload_file(r"C:\tmp\thumb.jpg", "owner/asset/thumb.jpg", "image/jpeg")
        assert calls["key"] == "owner/asset/thumb.jpg"          # destination first
        assert calls["path"] == r"C:\tmp\thumb.jpg"             # local file second
        assert calls["options"]["content-type"] == "image/jpeg"


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
