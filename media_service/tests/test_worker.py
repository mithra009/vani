"""Worker handlers: derivative naming, probe/proxy/thumbnail behaviour.

Storage is monkeypatched; ffprobe tests run against a real tiny clip when ffmpeg
is on PATH (skipped otherwise).
"""

import asyncio
import shutil
import subprocess

import pytest

from media_service import media, worker
from media_service.routes import derivative_keys

HAVE_FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
needs_ffmpeg = pytest.mark.skipif(not HAVE_FFMPEG, reason="ffmpeg/ffprobe not on PATH")

OWNER = "00000000-0000-0000-0000-000000000001"
ASSET = "22222222-2222-2222-2222-222222222222"


def make_job(**over):
    base = {
        "id": "33333333-3333-3333-3333-333333333333",
        "asset_id": ASSET,
        "kind": "probe",
        "status": "RUNNING",
        "attempts": 1,
        "storage_key": f"{OWNER}/{ASSET}/source.mp4",
        "deleted_at": None,
    }
    base.update(over)
    return base


@pytest.fixture(scope="module")
def tiny_mp4(tmp_path_factory):
    if not HAVE_FFMPEG:
        pytest.skip("ffmpeg/ffprobe not on PATH")
    p = tmp_path_factory.mktemp("worker") / "tiny.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         "testsrc=duration=1:size=128x96:rate=10", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         str(p)],
        check=True, capture_output=True,
    )
    return p


class TestDerivatives:
    def test_keys_share_prefix(self):
        thumb, proxy = derivative_keys(f"{OWNER}/{ASSET}/source.mp4")
        assert thumb == f"{OWNER}/{ASSET}/thumb.jpg"
        assert proxy == f"{OWNER}/{ASSET}/proxy.mp4"

    def test_every_kind_has_a_handler(self):
        assert set(worker.HANDLERS) == {"probe", "thumbnail", "proxy", "cleanup"}


@needs_ffmpeg
class TestProbeHandler:
    def test_probe_writes_metadata(self, monkeypatch, tiny_mp4, tmp_path):
        monkeypatch.setattr(worker.storage, "download", lambda key: tiny_mp4.read_bytes())
        out = asyncio.run(worker.handle_probe(make_job(), tmp_path))
        values = out["asset_values"]
        assert 900 <= values["duration_ms"] <= 1200
        assert values["metadata"]["has_video"] is True


@needs_ffmpeg
class TestThumbnailHandler:
    def test_thumbnail_uploads_jpg(self, monkeypatch, tiny_mp4, tmp_path):
        uploaded = {}
        monkeypatch.setattr(worker.storage, "download", lambda key: tiny_mp4.read_bytes())
        monkeypatch.setattr(worker.storage, "upload_file",
                            lambda path, key, ct: uploaded.update(key=key, ct=ct))
        out = asyncio.run(worker.handle_thumbnail(make_job(kind="thumbnail"), tmp_path))
        assert out == {}
        assert uploaded["key"] == f"{OWNER}/{ASSET}/thumb.jpg"
        assert uploaded["ct"] == "image/jpeg"


class TestProxyHandler:
    def test_duration_mismatch_fails_job(self, monkeypatch, tmp_path):
        """A proxy whose duration drifts from the source must not be published."""
        (tmp_path / "source").write_bytes(b"x")
        monkeypatch.setattr(worker.storage, "download", lambda key: b"x")
        calls = {"n": 0}

        def fake_probe(path):
            calls["n"] += 1
            # first call = source (10s), second call = proxy (5s)
            return {"duration": 10.0 if calls["n"] == 1 else 5.0,
                    "has_video": True, "has_audio": True,
                    "width": 1280, "height": 720, "fps": 25.0,
                    "video_codec": "h264", "audio_codec": "aac"}

        monkeypatch.setattr(worker.media, "probe", fake_probe)
        monkeypatch.setattr(worker.media, "run", lambda args: None)
        uploaded = {}
        monkeypatch.setattr(worker.storage, "upload_file",
                            lambda path, key, ct: uploaded.update(key=key))
        with pytest.raises(media.MediaError, match="duration"):
            asyncio.run(worker.handle_proxy(make_job(kind="proxy"), tmp_path))
        assert "key" not in uploaded  # nothing was published

    def test_skips_upload_when_asset_deleted(self, monkeypatch, tmp_path):
        (tmp_path / "source").write_bytes(b"x")
        monkeypatch.setattr(worker.storage, "download", lambda key: b"x")
        monkeypatch.setattr(worker.media, "probe", lambda p: {
            "duration": 1.0, "has_video": True, "has_audio": True,
            "width": 128, "height": 96, "fps": 10.0,
            "video_codec": "h264", "audio_codec": None})
        monkeypatch.setattr(worker.media, "run", lambda args: None)
        monkeypatch.setattr(worker.storage, "upload_file",
                            lambda *a: pytest.fail("must not upload a deleted asset"))
        with pytest.raises(worker.Skip):
            asyncio.run(worker.handle_proxy(
                make_job(kind="proxy", deleted_at=object()), tmp_path))
