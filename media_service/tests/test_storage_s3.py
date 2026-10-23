"""S3 backend of media_service.storage against moto's in-memory S3 (no network, no AWS account).
Skipped when moto isn't installed (pip install moto)."""

from urllib.parse import parse_qs, urlparse

import pytest

moto = pytest.importorskip("moto")

from media_service import storage  # noqa: E402

BUCKET = "vaani-video-store"
REGION = "ap-south-1"


@pytest.fixture()
def s3(monkeypatch, tmp_path):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    monkeypatch.setattr(storage, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(storage, "S3_BUCKET", BUCKET)
    monkeypatch.setattr(storage, "AWS_REGION", REGION)
    storage.s3.cache_clear()
    storage._url_cache.clear()
    with moto.mock_aws():
        storage.s3().create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": REGION})
        yield storage
    storage.s3.cache_clear()


def test_round_trip(s3, tmp_path):
    f = tmp_path / "clip.wav"
    f.write_bytes(b"RIFF" + b"\0" * 100)
    s3.upload_file(str(f), "u1/a1/voice.wav", "audio/wav")
    assert s3.object_info("u1/a1/voice.wav") == {"name": "voice.wav", "size": 104, "mimetype": "audio/wav"}
    assert s3.object_info("u1/a1/missing.wav") is None
    assert s3.download("u1/a1/voice.wav").startswith(b"RIFF")
    (tmp_path / "t.jpg").write_bytes(b"jpg")
    s3.upload_file(str(tmp_path / "t.jpg"), "u1/a1/thumb.jpg", "image/jpeg")
    s3.upload_file(str(tmp_path / "t.jpg"), "u1/a1/sub/deeper.jpg", "image/jpeg")
    assert sorted(s3.list_folder("u1/a1")) == ["u1/a1/thumb.jpg", "u1/a1/voice.wav"]   # direct children only
    s3.remove(["u1/a1/thumb.jpg", "u1/a1/voice.wav"])
    assert s3.list_folder("u1/a1") == []
    s3.remove([])                                                                       # no-op


def test_signed_urls(s3):
    up = s3.create_signed_upload_url("u1/a2/source.mp4")
    assert up["method"] == "s3-put" and up["token"] == ""
    u = urlparse(up["url"])
    assert u.netloc.startswith(f"{BUCKET}.s3.") and u.path == "/u1/a2/source.mp4"
    q = parse_qs(u.query)
    assert "X-Amz-Signature" in q and q["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert REGION in q["X-Amz-Credential"][0]

    a = s3.create_signed_download_url("u1/a2/thumb.jpg", 3600)
    assert s3.create_signed_download_url("u1/a2/thumb.jpg", 3600) == a          # reused → browser cache hits
    s3.forget_signed_urls(["u1/a2/thumb.jpg"])
    assert "X-Amz-Signature" in s3.create_signed_download_url("u1/a2/thumb.jpg", 3600)


def test_overwrite_invalidates_cached_url(s3, tmp_path):
    (tmp_path / "x").write_bytes(b"1")
    s3.create_signed_download_url("k/x.jpg", 3600)
    assert ("k/x.jpg", 3600) in s3._url_cache
    s3.upload_file(str(tmp_path / "x"), "k/x.jpg", "image/jpeg")
    assert ("k/x.jpg", 3600) not in s3._url_cache


def test_ready_check_names_the_problem(s3, monkeypatch):
    import asyncio
    asyncio.run(s3.storage_ready())                       # bucket exists → fine
    monkeypatch.setattr(storage, "S3_BUCKET", "no-such-bucket")
    with pytest.raises(RuntimeError, match="no-such-bucket"):
        asyncio.run(s3.storage_ready())


def test_missing_region_fails_clearly(monkeypatch):
    monkeypatch.setattr(storage, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(storage, "S3_BUCKET", BUCKET)
    monkeypatch.setattr(storage, "AWS_REGION", "")
    storage.s3.cache_clear()
    with pytest.raises(RuntimeError, match="AWS_REGION"):
        storage.s3()
    storage.s3.cache_clear()
