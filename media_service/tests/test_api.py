"""API contract tests: uploads/init, complete, asset reads, preview-url, delete.

The database and storage layers are monkeypatched — no Supabase needed.
"""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from media_service import db, routes, storage

OWNER = "00000000-0000-0000-0000-000000000001"


def amock(value=None, error=None):
    """Async stand-in for a db coroutine: return `value` or raise `error`."""
    async def f(*args, **kwargs):
        if error is not None:
            raise error
        return value
    return f


def make_asset(**over):
    base = {
        "id": "11111111-1111-1111-1111-111111111111",
        "project_id": None,
        "owner_id": OWNER,
        "original_filename": "clip.mp4",
        "storage_key": f"{OWNER}/11111111-1111-1111-1111-111111111111/source.mp4",
        "size_bytes": 1234,
        "duration_ms": 60_000,
        "status": "INITIATED",
        "metadata_status": "PENDING",
        "thumbnail_status": "PENDING",
        "proxy_status": "PENDING",
        "metadata": None,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "deleted_at": None,
    }
    base.update(over)
    return base


@pytest.fixture
def client():
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(routes.router)
    app.state.pool = None
    return TestClient(app)


@pytest.fixture
def no_quota(monkeypatch):
    async def fake_quota(pool, owner_id):
        return (0, 0)

    monkeypatch.setattr(db, "quota", fake_quota)


# ------------------------------------------------------------------ init

def test_init_happy_path(client, monkeypatch, no_quota):
    asset = make_asset()

    async def fake_create(pool, owner_id, **kw):
        assert kw["original_filename"] == "clip.mp4"
        assert kw["storage_key"].endswith("/source.mp4")
        return asset

    monkeypatch.setattr(db, "create_asset", fake_create)
    monkeypatch.setattr(
        storage, "create_signed_upload_url",
        lambda key: {"url": f"https://x.supabase.co/storage/v1/object/sign/media/{key}?token=t",
                     "token": "t"},
    )
    r = client.post("/api/uploads/init", json={
        "original_filename": "clip.mp4", "size_bytes": 1234, "duration_ms": 60_000,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["assetId"] == asset["id"]
    assert body["uploadUrl"].startswith("https://")
    assert body["token"] == "t"
    assert body["asset"]["status"] == "INITIATED"
    # Signed URLs are returned to the client, never persisted on the asset row.
    assert "signedURL" not in body["asset"]


def test_init_rejects_bad_extension(client, no_quota):
    r = client.post("/api/uploads/init", json={
        "original_filename": "clip.avi", "size_bytes": 10, "duration_ms": None,
    })
    assert r.status_code == 400
    assert "MP4" in r.json()["detail"]


def test_init_rejects_oversize(client, no_quota):
    r = client.post("/api/uploads/init", json={
        "original_filename": "clip.mp4", "size_bytes": 500_000_001, "duration_ms": 1000,
    })
    assert r.status_code == 400


def test_init_enforces_quota(client, monkeypatch):
    async def full_quota(pool, owner_id):
        return (200, 0)

    monkeypatch.setattr(db, "quota", full_quota)
    r = client.post("/api/uploads/init", json={
        "original_filename": "clip.mp4", "size_bytes": 10, "duration_ms": 1000,
    })
    assert r.status_code == 400
    assert "full" in r.json()["detail"].lower()


# ------------------------------------------------------------------ complete

def test_complete_verifies_and_enqueues(client, monkeypatch):
    asset = make_asset()

    async def fake_complete(pool, asset_id, owner_id, size_bytes):
        assert size_bytes == 1234
        return make_asset(status="UPLOADED")

    monkeypatch.setattr(db, "get_asset", amock(asset))
    monkeypatch.setattr(db, "complete_upload", fake_complete)
    monkeypatch.setattr(storage, "object_info", lambda key: {"size": 1234, "mimetype": "video/mp4"})

    r = client.post(f"/api/uploads/{asset['id']}/complete")
    assert r.status_code == 200
    assert r.json()["status"] == "UPLOADED"


def test_complete_rejects_size_mismatch(client, monkeypatch):
    asset = make_asset()
    monkeypatch.setattr(db, "get_asset", amock(asset))
    monkeypatch.setattr(storage, "object_info", lambda key: {"size": 999})
    r = client.post(f"/api/uploads/{asset['id']}/complete")
    assert r.status_code == 422


def test_complete_rejects_missing_object(client, monkeypatch):
    asset = make_asset()
    monkeypatch.setattr(db, "get_asset", amock(asset))
    monkeypatch.setattr(storage, "object_info", lambda key: None)
    r = client.post(f"/api/uploads/{asset['id']}/complete")
    assert r.status_code == 422


def test_complete_404_for_unknown_asset(client, monkeypatch):
    monkeypatch.setattr(db, "get_asset", amock(None))
    r = client.post("/api/uploads/does-not-exist/complete")
    assert r.status_code == 404


# ------------------------------------------------------------------ reads

def test_get_asset_with_thumbnail_url(client, monkeypatch):
    asset = make_asset(status="READY", thumbnail_status="READY",
                       proxy_status="READY", metadata_status="READY")
    monkeypatch.setattr(db, "get_asset", amock(asset))
    monkeypatch.setattr(storage, "create_signed_download_url",
                        lambda key, ttl: f"https://x.supabase.co/storage/v1/{key}?sig=s")
    r = client.get(f"/api/assets/{asset['id']}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "READY"
    assert body["thumbnail_url"].startswith("https://")
    assert body["created_at"].startswith("2026-01-01")


def test_list_assets(client, monkeypatch):
    monkeypatch.setattr(db, "list_assets", amock([make_asset()]))
    r = client.get("/api/assets")
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_preview_url_not_ready(client, monkeypatch):
    asset = make_asset()  # proxy still PENDING
    monkeypatch.setattr(db, "get_asset", amock(asset))
    r = client.get(f"/api/assets/{asset['id']}/preview-url")
    assert r.status_code == 409


def test_preview_url_ready(client, monkeypatch):
    asset = make_asset(status="READY", proxy_status="READY")
    monkeypatch.setattr(db, "get_asset", amock(asset))
    monkeypatch.setattr(storage, "create_signed_download_url",
                        lambda key, ttl: f"https://x.supabase.co/storage/v1/{key}?sig=s")
    r = client.get(f"/api/assets/{asset['id']}/preview-url")
    assert r.status_code == 200
    assert "proxy.mp4" in r.json()["url"]
    assert r.json()["expires_in"] > 0


# ------------------------------------------------------------------ delete

def test_delete_soft(client, monkeypatch):
    asset = make_asset()
    monkeypatch.setattr(db, "soft_delete", amock(asset))
    r = client.delete(f"/api/assets/{asset['id']}")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_delete_404(client, monkeypatch):
    monkeypatch.setattr(db, "soft_delete", amock(None))
    r = client.delete("/api/assets/nope")
    assert r.status_code == 404


# ------------------------------------------------------------------ misc

def test_cors_allows_frontend():
    from media_service.main import app

    client = TestClient(app)  # no context manager → lifespan (DB connect) doesn't run
    r = client.options("/api/assets", headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET",
    })
    assert r.status_code in (200, 204)
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"


def test_connection_string_guard():
    with pytest.raises(RuntimeError, match="6543"):
        db.check_connection_string("postgres://user:pass@host:6543/postgres")
    db.check_connection_string("postgres://user:pass@host:5432/postgres")  # fine
