"""Worker end to end on real audio with fake providers; db + storage replaced in memory.

Checks the no-silent-failure contract: every job ends DONE / SKIPPED / FAILED, and a final
failure is written to the project or chunk the user sees.
"""

import asyncio
import shutil
import subprocess
from pathlib import Path

import pytest

from editor_service import db, providers, worker
from editor_service.errors import OutputInvalid, ProviderError

needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not on PATH")
OWNER = "00000000-0000-0000-0000-000000000001"


class Mem:
    """Just enough of db.* and storage for the worker."""

    def __init__(self, project):
        self.project, self.chunks, self.artifacts, self.blobs = project, {}, {}, {}
        self.jobs, self.finished, self.project_fail, self.chunk_fail = [], [], None, {}
        self.stages = []

    def install(self, mp):
        mem = self

        async def artifact_get(_, owner, key):
            return mem.artifacts.get((owner, key))

        async def artifact_put(_, owner, key, kind, skey, meta):
            mem.artifacts[(owner, key)] = {"storage_key": skey, "meta": meta}

        async def replace_chunks(_, pid, owner, rows, dur):
            mem.chunks = {f"c{r['idx']}": dict(r, id=f"c{r['idx']}", revision=1, status="pending", speed=1.0)
                          for r in rows}
            mem.jobs += [{"id": f"j{c}", "kind": "tts", "project_id": pid, "chunk_id": c, "chunk_revision": 1,
                          "attempts": 1} for c in mem.chunks]

        async def chunk_generating(_, cid, rev):
            c = mem.chunks.get(cid)
            return dict(c) if c and c["revision"] == rev else None

        async def chunk_audio_ready(_, cid, rev, key, dur):
            c = mem.chunks[cid]
            if c["revision"] != rev:
                return False
            c.update(audio_key=key, audio_duration_s=dur, status="ready")
            return True

        async def chunk_failed(_, cid, rev, code, msg):
            mem.chunk_fail[cid] = (code, msg)

        async def fail_project(_, pid, code, msg):
            mem.project_fail = (code, msg)

        async def finish_job(_, job, *, outcome, code=None, error=None, retry=False):
            final = outcome != "FAILED" or not retry or job["attempts"] >= 4
            mem.finished.append((job["id"], outcome, code, final))
            return outcome == "FAILED" and final

        async def claim_job(_):
            return mem.jobs.pop(0) if mem.jobs else None

        async def project_for_job(_, job):
            return mem.project

        async def set_stage(_, pid, stage):
            mem.stages.append(stage)

        for fn in (artifact_get, artifact_put, replace_chunks, chunk_generating, chunk_audio_ready,
                   chunk_failed, fail_project, finish_job, claim_job, project_for_job, set_stage):
            mp.setattr(db, fn.__name__, fn)

        async def download(key, dst: Path):
            dst.write_bytes(mem.blobs[key])
            return dst

        async def upload_bytes(data, key, ct, workdir):
            mem.blobs[key] = data

        async def no_limit(*a, **k):        # rate limiting has its own DB tests (test_ratelimit.py)
            return None
        mp.setattr(worker.ratelimit, "acquire", no_limit)
        mp.setattr(worker, "download", download)
        mp.setattr(worker, "upload_bytes", upload_bytes)


@pytest.fixture(scope="module")
def speechy_mp4(tmp_path_factory):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not on PATH")
    p = tmp_path_factory.mktemp("w") / "src.mp4"
    # Two tone bursts with silence between: the fake STT finds two speech regions.
    gate = "volume='if(between(t,0.5,2.5)+between(t,3.5,5.5),1,0)':eval=frame"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "testsrc=duration=6:size=128x96:rate=10",
         "-f", "lavfi", "-i", "sine=f=220:d=6",
         "-filter_complex", f"[1:a]{gate}[a]",
         "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(p)],
        check=True,
    )
    return p.read_bytes()


def project(**over):
    p = {"id": "p1", "owner_id": OWNER, "input_kind": "video_audio", "asset_key": f"{OWNER}/a/source.mp4",
         "narration_key": None, "script_text": None, "src_lang": "hi-IN", "tgt_lang": "hi-IN",
         "voice": {"mode": "persona", "voice_id": "anu"}, "duration_s": 6.0}
    p.update(over)
    return p


def generate_job(attempts=1):
    return [{"id": "g", "kind": "generate", "project_id": "p1", "attempts": attempts}]


def run_all():
    async def go():
        while await worker.process_one(None):
            pass
    asyncio.run(go())


@needs_ffmpeg
def test_video_audio_generates_and_voices_every_chunk(monkeypatch, speechy_mp4):
    mem = Mem(project())
    mem.blobs[mem.project["asset_key"]] = speechy_mp4
    mem.install(monkeypatch)
    mem.jobs = generate_job()
    run_all()
    assert mem.chunks, "no chunks produced"
    assert all(c["status"] == "ready" and c["audio_duration_s"] > 0 for c in mem.chunks.values())
    assert all(o == "DONE" for _, o, _, _ in mem.finished), mem.finished
    starts = [c["anchor_src_s"] for c in sorted(mem.chunks.values(), key=lambda c: c["idx"])]
    assert starts == sorted(starts) and 0.3 < starts[0] < 1.0


@needs_ffmpeg
def test_narration_is_cleaned_then_transcribed(monkeypatch, speechy_mp4, tmp_path):
    src = tmp_path / "n.mp4"
    src.write_bytes(speechy_mp4)
    webm = tmp_path / "n.webm"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src), "-vn", "-c:a", "libopus", str(webm)], check=True)
    mem = Mem(project(input_kind="narration", narration_key=f"{OWNER}/projects/p1/narration.webm"))
    mem.blobs[mem.project["narration_key"]] = webm.read_bytes()
    mem.install(monkeypatch)
    mem.jobs = generate_job()
    run_all()
    assert mem.chunks and all(c["status"] == "ready" for c in mem.chunks.values())


@needs_ffmpeg
def test_second_tts_run_is_a_cache_hit(monkeypatch, speechy_mp4):
    mem = Mem(project())
    mem.blobs[mem.project["asset_key"]] = speechy_mp4
    mem.install(monkeypatch)
    mem.jobs = generate_job()
    run_all()
    calls = []
    real = providers.Speech.tts

    async def counting(self, *a, **k):
        calls.append(a)
        return await real(self, *a, **k)
    monkeypatch.setattr(providers.Speech, "tts", counting)
    for c in mem.chunks.values():
        c["revision"] += 1
    mem.jobs = [{"id": f"r{c}", "kind": "tts", "project_id": "p1", "chunk_id": c, "chunk_revision": 2, "attempts": 1}
                for c in mem.chunks]
    run_all()
    assert calls == []
    assert all(c["status"] == "ready" for c in mem.chunks.values())


@needs_ffmpeg
def test_video_without_audio_fails_with_a_reason(monkeypatch, tmp_path):
    p = tmp_path / "silent.mp4"
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=duration=1:size=64x48:rate=5",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(p)], check=True)
    mem = Mem(project())
    mem.blobs[mem.project["asset_key"]] = p.read_bytes()
    mem.install(monkeypatch)
    mem.jobs = generate_job()
    run_all()
    assert mem.project_fail[0] == "no_audio"


def test_script_input_places_end_to_end_and_flags_overflow(monkeypatch):
    text = "One short line. This second sentence is deliberately long enough to run past the end of a tiny video."
    mem = Mem(project(input_kind="script", script_text=text, duration_s=3.0, tgt_lang="en-IN"))
    mem.install(monkeypatch)
    mem.jobs = generate_job()
    run_all()
    cs = sorted(mem.chunks.values(), key=lambda c: c["idx"])
    assert [c["overflow"] for c in cs] == [False, True]
    assert cs[0]["text"].startswith("[en-IN] ")           # fake translation ran
    assert cs[0]["source_text"] == "One short line."
    assert all(c["status"] == "ready" for c in cs)


def test_stale_tts_job_is_skipped_not_written(monkeypatch):
    mem = Mem(project(input_kind="script", script_text="Hello."))
    mem.install(monkeypatch)
    mem.jobs = generate_job()
    asyncio.run(worker.process_one(None))                  # generate only
    mem.chunks["c0"]["revision"] = 2                        # the user edited meanwhile
    run_all()
    assert mem.chunks["c0"]["status"] == "pending"
    assert mem.finished[-1][1] == "SKIPPED"


def test_invalid_chunking_fails_the_project_with_a_reason(monkeypatch):
    mem = Mem(project(input_kind="script", script_text="Hello world."))
    mem.install(monkeypatch)

    async def rewrite(self, text, lang):
        return [{"text": "Hi world.", "emotion_tag": "neutral"}]
    monkeypatch.setattr(providers.FakeLanguage, "chunk", rewrite)
    mem.jobs = generate_job(attempts=4)
    run_all()
    assert mem.finished == [("g", "FAILED", "chunking_invalid", True)]
    assert mem.project_fail[0] == "chunking_invalid" and "without changing it" in mem.project_fail[1]


def test_transient_provider_error_retries_then_lands_on_the_chunk(monkeypatch):
    mem = Mem(project(input_kind="script", script_text="Hello."))
    mem.install(monkeypatch)
    mem.jobs = generate_job()
    asyncio.run(worker.process_one(None))

    async def down(self, *a, **k):
        raise ProviderError("Gnani is unavailable: 503")
    monkeypatch.setattr(providers.Speech, "tts", down)
    job = mem.jobs[0]
    mem.jobs = [dict(job, attempts=1)]
    asyncio.run(worker.process_one(None))
    assert mem.finished[-1] == (job["id"], "FAILED", "provider_unavailable", False) and not mem.chunk_fail
    mem.jobs = [dict(job, attempts=4)]
    asyncio.run(worker.process_one(None))
    assert mem.chunk_fail["c0"][0] == "provider_unavailable"


def test_unexpected_crash_is_recorded_not_swallowed(monkeypatch):
    mem = Mem(project(input_kind="script", script_text="Hello."))
    mem.install(monkeypatch)

    async def boom(*a, **k):
        raise KeyError("surprise")
    monkeypatch.setattr(worker, "cut_chunks", boom)
    mem.jobs = generate_job()
    run_all()
    assert mem.finished == [("g", "FAILED", "internal", True)]
    assert mem.project_fail[0] == "internal"


def test_video_without_known_duration_fails_clearly(monkeypatch):
    mem = Mem(project(duration_s=None))
    mem.install(monkeypatch)
    mem.jobs = generate_job()
    run_all()
    assert mem.project_fail[0] == "asset_not_ready"


def test_translation_validation():
    items = [{"id": 0, "text": "a"}, {"id": 1, "text": "b"}]
    assert providers.validate_translation(items, [{"id": 0, "text": " x "}, {"id": 1, "text": "y"}]) == {0: "x", 1: "y"}
    for bad in ([{"id": 0, "text": "x"}], [{"id": 0, "text": "x"}, {"id": 1, "text": " "}], "nope"):
        with pytest.raises(OutputInvalid):
            providers.validate_translation(items, bad)
