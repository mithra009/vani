"""Uploads are read only as their own media, and one user can't fill the shared job worker."""

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import main, media, store
from backend.app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def playlist(tmp_path) -> Path:
    """An HLS playlist whose one segment is another media file on this machine."""
    other = tmp_path / "someone_elses.ts"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc=size=64x64:rate=5:duration=2",
                    "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                    "-c:v", "mpeg2video", "-c:a", "mp2", "-f", "mpegts", str(other)], check=True)
    p = tmp_path / "x.m3u8"
    p.write_text("#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:2\n#EXT-X-MEDIA-SEQUENCE:0\n"
                 f"#EXTINF:2.0,\n{other.resolve().as_posix()}\n#EXT-X-ENDLIST\n")
    return p


def test_client_extension_is_not_kept():
    assert main.safe_ext("x.m3u8", main.VIDEO_EXTS, ".mp4") == ".mp4"
    assert main.safe_ext("clip.MOV", main.VIDEO_EXTS, ".mp4") == ".mov"
    assert main.safe_ext(None, main.AUDIO_EXTS, ".webm") == ".webm"


def test_playlist_upload_is_not_followed(client, playlist):
    with open(playlist, "rb") as f:
        r = client.post("/api/jobs", files={"video": ("x.m3u8", f, "application/vnd.apple.mpegurl")},
                        data={"src_lang": "auto", "tgt_lang": "ta-IN", "mode": "dub"})
    assert r.status_code == 400, r.text


def test_probe_refuses_network_inputs(tmp_path):
    with pytest.raises(media.MediaError):
        media.probe(Path("http://169.254.169.254/latest/meta-data/"))


def test_active_job_cap(client, monkeypatch, playlist):
    busy = [{"status": "transcribing"}, {"status": "dubbing"}]
    monkeypatch.setattr(store, "list_jobs", lambda user_id=None: busy)
    with open(playlist, "rb") as f:
        r = client.post("/api/jobs", files={"video": ("talk.mp4", f, "video/mp4")},
                        data={"src_lang": "auto", "tgt_lang": "ta-IN", "mode": "dub"})
    assert r.status_code == 429, r.text
