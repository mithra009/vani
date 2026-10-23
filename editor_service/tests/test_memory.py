"""Memory: nothing large is held in RAM, caches stay bounded, repeated work doesn't grow memory.

Measured with tracemalloc (Python allocations). "Growth" is measured after a warm-up round, so
one-time caches (imports, compiled regexes, first-call setup) don't count as leaks.
"""

import asyncio
import gc
import tracemalloc

import pytest

from editor_service import timeline as tl

MB = 1024 * 1024


def _growth(fn, rounds: int, warmup: int = 2) -> int:
    """Bytes still allocated after `rounds` more calls, relative to after the warm-up."""
    for _ in range(warmup):
        fn()
    gc.collect()
    tracemalloc.start()
    base = tracemalloc.get_traced_memory()[0]
    for _ in range(rounds):
        fn()
    gc.collect()
    now = tracemalloc.get_traced_memory()[0]
    tracemalloc.stop()
    return now - base


# ------------------------------------------------------------------ large files never sit in RAM

def test_s3_download_streams_to_disk(monkeypatch, tmp_path):
    """A 96 MB object downloads with a small, bounded footprint in this process. The fake S3
    runs as a separate process (moto server), so only our side is measured."""
    pytest.importorskip("flask")
    import socket
    import subprocess
    import sys
    import time
    from media_service import storage
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    srv = subprocess.Popen([sys.executable, "-m", "moto.server", "-p", str(port)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                socket.create_connection(("127.0.0.1", port), timeout=0.2).close(); break
            except OSError:
                time.sleep(0.1)
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "t")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "t")
        monkeypatch.setattr(storage, "STORAGE_BACKEND", "s3")
        monkeypatch.setattr(storage, "S3_BUCKET", "mem-test")
        monkeypatch.setattr(storage, "AWS_REGION", "ap-south-1")
        monkeypatch.setattr(storage, "S3_ENDPOINT_URL", f"http://127.0.0.1:{port}")
        storage.s3.cache_clear()
        storage.s3().create_bucket(Bucket="mem-test", CreateBucketConfiguration={"LocationConstraint": "ap-south-1"})
        size = 96 * MB
        src = tmp_path / "src.bin"
        with open(src, "wb") as f:
            for _ in range(size // MB):
                f.write(b"Z" * MB)
        storage.upload_file(str(src), "k/video.mp4", "video/mp4")
        gc.collect()

        tracemalloc.start()
        n = storage.download_to("k/video.mp4", str(tmp_path / "out.bin"))
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        tracemalloc.start()
        whole = storage.download("k/video.mp4")            # the old way, for comparison
        _, peak_old = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        del whole
    finally:
        srv.terminate(); srv.wait(timeout=10)
        storage.s3.cache_clear()
    assert n == size
    print(f"download_to peak {peak / MB:.1f} MB vs whole-file download {peak_old / MB:.1f} MB for {size / MB:.0f} MB")
    assert peak < 48 * MB, f"download_to peaked at {peak / MB:.0f} MB for a {size / MB:.0f} MB file"
    assert peak_old > size                                   # sanity: the old path really held it all


# ------------------------------------------------------------------ caches stay bounded

def test_signed_url_cache_is_bounded(monkeypatch):
    from media_service import storage
    monkeypatch.setattr(storage, "_sign_download", lambda key, ttl: f"https://x/{key}?sig=1")
    storage._url_cache.clear()
    for i in range(storage._URL_CACHE_MAX * 2):
        storage.create_signed_download_url(f"k/{i}.jpg", 3600)
    assert len(storage._url_cache) <= storage._URL_CACHE_MAX
    storage._url_cache.clear()


# ------------------------------------------------------------------ repeated work doesn't grow memory

def test_timeline_edit_and_undo_does_not_leak():
    doc = tl.default_doc(600)

    def session():
        d, invs = doc, []
        for i in range(200):        # split the first clip a little further in each time
            first = d["video"][0]
            d, inv = tl.apply(d, {"type": "video.split", "clip_id": first["id"], "at_src": first["src_in"] + 2.5,
                                  "new_id": f"c{i}"}, source_s=600)
            d, mv = tl.apply(d, {"type": "video.move", "clip_id": f"c{i}", "index": 0}, source_s=600)
            invs += [inv, mv]
        for inv in reversed(invs):
            d, _ = tl.apply(d, inv, source_s=600)
        assert d["video"] == doc["video"]
    assert _growth(session, rounds=20) < 256 * 1024


def test_layout_does_not_leak():
    doc = tl.default_doc(600)
    chunks = [{"id": f"c{i}", "idx": i, "anchor_src_s": i * 3.0, "anchor_len_s": 2.5, "audio_duration_s": 2.6}
              for i in range(190)]
    assert _growth(lambda: tl.layout(doc, chunks), rounds=300) < 256 * 1024


def test_worker_job_loop_does_not_leak(monkeypatch):
    """300 tts jobs through the real worker loop (cache-hit path: no new blobs by design)."""
    from editor_service import worker
    from editor_service.tests.test_worker import Mem, project
    mem = Mem(project(input_kind="script", script_text="One line. Two line. Three line."))
    mem.install(monkeypatch)
    mem.jobs = [{"id": "g", "kind": "generate", "project_id": "p1", "attempts": 1}]

    async def drain():
        while await worker.process_one(None):
            pass
    asyncio.run(drain())                       # generate + first tts (fills the artifact cache)
    chunk_ids = list(mem.chunks)

    def batch():
        for c in chunk_ids:
            mem.chunks[c]["revision"] += 1
            mem.jobs.append({"id": f"j{c}", "kind": "tts", "project_id": "p1", "chunk_id": c,
                             "chunk_revision": mem.chunks[c]["revision"], "attempts": 1})
        asyncio.run(drain())
        mem.finished.clear()                   # the fake's own log, not the worker's state
    assert _growth(batch, rounds=100) < 512 * 1024


def test_backend_subscribers_are_released():
    from backend.app import jobs
    for i in range(5000):
        q = jobs.subscribe(f"job-{i}")
        jobs.unsubscribe(f"job-{i}", q)
    assert not any(k.startswith("job-") for k in jobs._subscribers)


def test_backend_project_cache_is_bounded_and_keeps_unsaved(monkeypatch):
    from backend.app import store
    monkeypatch.setattr(store, "MEM_CACHE_MAX", 50)
    store._mem.clear(); store._dirty.clear()
    with store._flush_cv:
        for i in range(500):
            store._remember(f"p{i}", {"id": f"p{i}", "data": "x" * 1000})
    assert len(store._mem) == 50
    assert "p499" in store._mem and "p0" not in store._mem          # oldest evicted first
    # Unflushed documents are never evicted, even over the cap.
    with store._flush_cv:
        store._dirty["p450"] = store._mem["p450"]
        for i in range(500, 600):
            store._remember(f"p{i}", {"id": f"p{i}"})
    assert "p450" in store._mem
    store._mem.clear(); store._dirty.clear()
