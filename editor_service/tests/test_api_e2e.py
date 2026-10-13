"""All three phases through the HTTP API + worker on a real Postgres, storage in memory,
fake providers, real ffmpeg. Skips without DATABASE_URL_TEST (see test_db.py)."""

import asyncio
import shutil
import subprocess

import pytest

from editor_service.tests.test_db import OWNER, URL, fresh_pool

pytestmark = [pytest.mark.skipif(not URL, reason="DATABASE_URL_TEST not set"),
              pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")]


@pytest.fixture()
def env(monkeypatch, tmp_path):
    from media_service import storage
    blobs = {}

    monkeypatch.setattr(storage, "create_signed_upload_url", lambda key: {"url": f"https://up/{key}", "token": "t"})
    monkeypatch.setattr(storage, "create_signed_download_url", lambda key, ttl=3600: f"https://dl/{key}")
    monkeypatch.setattr(storage, "object_info", lambda key: {"size": len(blobs[key])} if key in blobs else None)
    monkeypatch.setattr(storage, "download", lambda key: blobs[key])

    def upload_file(path, key, ct):
        blobs[key] = open(path, "rb").read()
    monkeypatch.setattr(storage, "upload_file", upload_file)

    src = tmp_path / "src.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=8:size=320x240:rate=25",
                    "-f", "lavfi", "-i", "sine=f=220:d=8", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-shortest", str(src)], check=True)

    async def setup():
        pool = await fresh_pool()
        await pool.execute(
            "insert into assets (id, owner_id, original_filename, storage_key, status, duration_ms) "
            "values ('11111111-1111-1111-1111-111111111111', $1, 'v.mp4', $2, 'READY', 8000)",
            OWNER, f"{OWNER}/a/source.mp4")
        await pool.close()
    asyncio.run(setup())
    blobs[f"{OWNER}/a/source.mp4"] = src.read_bytes()
    return blobs


def drain():
    from editor_service import db, worker

    async def go():
        pool = await db.connect(URL)
        try:
            n = 0
            while await worker.process_one(pool):
                n += 1
            return n
        finally:
            await pool.close()
    return asyncio.run(go())


def test_script_to_export(env):
    from fastapi.testclient import TestClient
    from editor_service.main import app

    with TestClient(app) as c:
        r = c.post("/api/editor/projects", json={
            "asset_id": "11111111-1111-1111-1111-111111111111", "name": "Demo", "input_kind": "script",
            "script_text": "Welcome to the demo. Haha, this part is funny! And this is the end.",
            "src_lang": "en-IN", "tgt_lang": "en-IN", "voice": {"mode": "persona", "voice_id": "anu"}})
        assert r.status_code == 201, r.text
        pid = r.json()["id"]

        # Export before audio exists is refused, loudly.
        assert c.post(f"/api/editor/projects/{pid}/exports", json={"format": "mp4", "height": 720}).status_code == 409

        assert drain() >= 4
        data = c.get(f"/api/editor/projects/{pid}").json()
        assert data["project"]["status"] == "editing", data["project"]
        chunks = data["chunks"]
        assert [ch["emotion_tag"] for ch in chunks] == ["neutral", "laugh", "neutral"]
        assert all(ch["status"] == "ready" and ch["has_audio"] for ch in chunks)

        # Content edit: If-Match required, stale revision → 409, then regenerate.
        cid = chunks[0]["id"]
        assert c.patch(f"/api/editor/projects/{pid}/chunks/{cid}", json={"speed": 1.1}).json()["code"] == "revision_required"
        assert c.patch(f"/api/editor/projects/{pid}/chunks/{cid}", json={"speed": 1.1}, headers={"If-Match": "9"}).status_code == 409
        r = c.patch(f"/api/editor/projects/{pid}/chunks/{cid}", json={"speed": 1.1}, headers={"If-Match": "1"})
        assert r.status_code == 200 and r.json()["status"] == "pending"
        bad = c.patch(f"/api/editor/projects/{pid}/chunks/{cid}", json={"emotion_tag": "angry"}, headers={"If-Match": "2"})
        assert bad.status_code == 422 and bad.json()["code"] == "input_invalid"
        drain()

        # Timeline: cut the last 2 s, conflict on a stale base, captions on.
        tl = c.get(f"/api/editor/projects/{pid}/timeline").json()
        assert tl["version"] == 1
        ops = [{"type": "video.trim", "clip_id": "vc0", "src_in": 0, "src_out": 6.0},
               {"type": "track.set", "track": "captions", "fields": {"enabled": True}}]
        r = c.post(f"/api/editor/projects/{pid}/timeline/ops", json={"base_version": 1, "ops": ops})
        assert r.status_code == 200 and r.json()["version"] == 2
        r = c.post(f"/api/editor/projects/{pid}/timeline/ops", json={"base_version": 1, "ops": ops})
        assert r.status_code == 409 and r.json()["version"] == 2 and r.json()["doc"]["video"][0]["src_out"] == 6.0
        r = c.post(f"/api/editor/projects/{pid}/timeline/ops", json={"base_version": 2, "ops": [{"type": "nope"}]})
        assert r.status_code == 422 and "Op 0" in r.json()["message"]

        # Export: bad combos rejected; a real render; identical request served from cache.
        assert c.post(f"/api/editor/projects/{pid}/exports", json={"format": "mp3", "height": 720}).status_code == 422
        r = c.post(f"/api/editor/projects/{pid}/exports", json={"format": "mp4", "height": 720, "captions": "srt"})
        assert r.status_code == 202, r.text
        drain()
        exports = c.get(f"/api/editor/projects/{pid}/exports").json()
        ready = [e for e in exports if e["status"] == "ready"]
        assert ready, exports
        assert ready[0]["progress"] == 1 and ready[0]["has_captions"]
        url = c.get(f"/api/editor/projects/{pid}/exports/{ready[0]['id']}/url").json()
        out_key = url["url"].removeprefix("https://dl/")
        assert env[out_key][:12].find(b"ftyp") != -1
        assert b"-->" in env[url["captions_url"].removeprefix("https://dl/")]
        again = c.post(f"/api/editor/projects/{pid}/exports", json={"format": "mp4", "height": 720, "captions": "srt"}).json()
        assert again["status"] == "ready"


def test_export_failure_is_visible(env, monkeypatch):
    from fastapi.testclient import TestClient
    from editor_service import worker
    from editor_service.errors import MediaFailed
    from editor_service.main import app

    with TestClient(app) as c:
        pid = c.post("/api/editor/projects", json={
            "asset_id": "11111111-1111-1111-1111-111111111111", "name": "F", "input_kind": "script",
            "script_text": "One line.", "src_lang": "en-IN", "tgt_lang": "en-IN",
            "voice": {"mode": "persona", "voice_id": "anu"}}).json()["id"]
        drain()

        async def broken(*a, **k):
            raise MediaFailed("ffmpeg failed (1): something", "export_failed")
        monkeypatch.setattr(worker, "run_ffmpeg", broken)
        c.post(f"/api/editor/projects/{pid}/exports", json={"format": "webm", "height": 480})
        drain()
        e = c.get(f"/api/editor/projects/{pid}/exports").json()[0]
        assert (e["status"], e["error_code"]) == ("failed", "export_failed") and "ffmpeg failed" in e["error_message"]
