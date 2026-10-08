"""Full pipeline through the HTTP API with fake providers and real ffmpeg."""

import subprocess
import time
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

from backend.app.main import app
from backend.app import media

DUR = 24.0


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def video(tmp_path_factory) -> Path:
    """24 s video whose audio has 'speech' bursts (2.5 s on, 1.5 s off)."""
    d = tmp_path_factory.mktemp("media")
    p = d / "talk.mp4"
    expr = "0.4*sin(2*PI*180*t)*gt(mod(t\\,4)\\,1.5)"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=25:duration={DUR}",
                    "-f", "lavfi", "-i", f"aevalsrc={expr}:s=48000:d={DUR}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(p)], check=True)
    return p


def wait_for(client, job_id, status, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/api/jobs/{job_id}").json()
        if j["status"] == status:
            return j
        assert j["status"] != "failed", j.get("error")
        time.sleep(0.3)
    raise AssertionError(f"timed out waiting for {status}, last {j['status']}")


def test_health(client):
    assert client.get("/api/health").json()["providers"] == "fake"


def test_dub_persona_end_to_end(client, video):
    with open(video, "rb") as f:
        r = client.post("/api/jobs", files={"video": ("talk.mp4", f, "video/mp4")},
                        data={"src_lang": "auto", "tgt_lang": "ta-IN", "mode": "dub"})
    assert r.status_code == 200, r.text
    job = wait_for(client, r.json()["id"], "review")

    segs = job["segments"]
    assert 4 <= len(segs) <= 8, [ (s["start_s"], s["end_s"]) for s in segs ]
    for s in segs:                                    # timestamps line up with the bursts
        assert (s["start_s"] % 4) == pytest.approx(1.5, abs=0.15)
    assert all(s["slot_end_s"] >= s["end_s"] for s in segs)

    segs[0]["src_text"] = "Edited first line"
    segs[1]["keep_original"] = True
    segs[2]["emotion"], segs[2]["emotion_overridden"] = "angry", True
    r = client.patch(f"/api/jobs/{job['id']}/segments", json={"segments": segs})
    assert r.json()["segments"][0]["src_text"] == "Edited first line"

    r = client.post(f"/api/jobs/{job['id']}/dub", json={"voice": {"mode": "persona", "voice_id": "Asmita"}, "bg_mode": "duck"})
    assert r.status_code == 200, r.text
    done = wait_for(client, job["id"], "done")

    st = done["stats"]
    assert st["segments"] == len(segs) - 1
    assert st["duration_error_samples"] < 48000 * 0.05     # container-level check; see probe below
    assert done["segments"][0]["tgt_text"].endswith("Edited first line")
    assert done["segments"][1]["tgt_text"] == done["segments"][1]["src_text"]

    out = client.get(f"/api/jobs/{job['id']}/output.mp4")
    assert out.status_code == 200 and len(out.content) > 10000
    p = video.parent / "out.mp4"
    p.write_bytes(out.content)
    info = media.probe(p)
    assert info["has_audio"] and info["has_video"]
    assert abs(info["duration"] - DUR) < 0.05

    srt = client.get(f"/api/jobs/{job['id']}/subs.target.srt").text
    assert "-->" in srt


def test_dubbed_lines_start_where_originals_start(client, video):
    """The voice track must have sound starting at each segment's start (absolute placement)."""
    jobs = client.get("/api/jobs").json()
    done = [j for j in jobs if j["status"] == "done" and j["mode"] == "dub"][0]
    from backend.app import store
    d = store.job_dir(done["id"])
    x, sr = sf.read(str(d / "voice_raw.wav"))
    full = client.get(f"/api/jobs/{done['id']}").json()
    for s in full["segments"]:
        if s["keep_original"]:
            continue
        i = int(s["start_s"] * sr)
        before = np.abs(x[max(0, i - int(0.05 * sr)): i]).max(initial=0)
        after = np.abs(x[i: i + int(0.2 * sr)]).max()
        assert after > 0.05 and before < after * 0.3, (s["start_s"], before, after)


def test_narrate_own_voice(client, video, tmp_path):
    with open(video, "rb") as f:
        r = client.post("/api/jobs", files={"video": ("talk.mp4", f, "video/mp4")},
                        data={"src_lang": "hi-IN", "tgt_lang": "same", "mode": "narrate"})
    job = r.json()
    assert job["status"] == "awaiting_narration"

    sr = 48000
    t = np.arange(int(sr * 8)) / sr
    narr = (0.3 * np.sin(2 * np.pi * 200 * t) * ((t % 3) < 2)).astype(np.float32)
    wav = tmp_path / "narr.wav"
    sf.write(str(wav), narr, sr)
    with open(wav, "rb") as f:
        r = client.post(f"/api/jobs/{job['id']}/narration", files={"audio": ("narr.wav", f, "audio/wav")},
                        data={"offset_s": "5"})
    assert r.status_code == 200, r.text
    rev = wait_for(client, job["id"], "review")
    assert rev["tgt_lang"] == rev["src_lang"] == "hi-IN"
    assert all(5.0 <= s["start_s"] < 13.2 for s in rev["segments"])
    assert rev["segments"][0]["start_s"] == pytest.approx(5.0, abs=0.15)

    r = client.post(f"/api/jobs/{job['id']}/dub", json={"voice": {"mode": "own"}, "bg_mode": "mute"})
    assert r.status_code == 200, r.text
    done = wait_for(client, job["id"], "done")
    assert done["stats"]["flagged"] == 0
    from backend.app import store
    x, sr = sf.read(str(store.job_dir(job["id"]) / "voice.wav"))
    assert np.abs(x[: int(4.9 * sr)]).max() < 0.01          # silent before the take
    assert np.abs(x[int(5.1 * sr): int(6.5 * sr)]).max() > 0.05


def test_clone_from_uploaded_sample(client, video, tmp_path):
    with open(video, "rb") as f:
        job = client.post("/api/jobs", files={"video": ("talk.mp4", f, "video/mp4")},
                          data={"src_lang": "hi-IN", "tgt_lang": "kn-IN", "mode": "dub"}).json()
    wait_for(client, job["id"], "review")
    sr = 16000
    sample = (0.2 * np.sin(2 * np.pi * 160 * np.arange(sr * 8) / sr)).astype(np.float32)
    wav = tmp_path / "me.wav"
    sf.write(str(wav), sample, sr)
    import json
    with open(wav, "rb") as f:
        r = client.post(f"/api/jobs/{job['id']}/dub",
                        files={"voice_sample": ("me.wav", f, "audio/wav")},
                        data={"settings": json.dumps({"voice": {"mode": "clone", "source": "upload", "consent": True}, "bg_mode": "duck"})})
    assert r.status_code == 200, r.text
    done = wait_for(client, job["id"], "done")
    assert done["voice"]["mode"] == "clone" and done["stats"]["segments"] > 0


def test_rejections(client, video):
    r = client.post(f"/api/jobs/nope/dub", json={})
    assert r.status_code == 404
    with open(video, "rb") as f:
        r = client.post("/api/jobs", files={"video": ("talk.mp4", f, "video/mp4")},
                        data={"src_lang": "hi-IN", "tgt_lang": "same", "mode": "dub"})
    assert r.status_code == 400
    r = client.post("/api/jobs", files={"video": ("x.mp4", b"not a video", "video/mp4")},
                    data={"src_lang": "hi-IN", "tgt_lang": "ta-IN"})
    assert r.status_code == 400
