"""Object storage helpers (server-side only): AWS S3 or the Supabase bucket.

STORAGE_BACKEND picks one (config.py): "s3" when S3_BUCKET is set, else "supabase". Every
caller uses the same functions, so media_service and editor_service don't know which.

Signed URLs are short-lived and never stored in the database. supabase-py returns
relative paths like "/object/sign/media/...?token=..." for some calls, so every
Supabase URL is normalized to an absolute one here.

Browser uploads differ by backend: Supabase takes a multipart PUT with the token in the URL;
S3 takes a raw-body PUT to a presigned URL. create_signed_upload_url returns `method` so the
frontend (libraryStore.uploadToStorage) sends the right request.
"""

from __future__ import annotations

import logging
import threading
import time
from functools import lru_cache
from typing import Any

from .config import (
    AWS_REGION, MEDIA_BUCKET, S3_BUCKET, S3_ENDPOINT_URL, SIGNED_URL_TTL_SECONDS, STORAGE_BACKEND, SUPABASE_SECRET_KEY,
    SUPABASE_URL, UPLOAD_URL_TTL_SECONDS,
)

log = logging.getLogger("media.storage")

if STORAGE_BACKEND not in ("s3", "supabase"):
    raise RuntimeError(f"STORAGE_BACKEND must be 's3' or 'supabase', got {STORAGE_BACKEND!r}.")


# ------------------------------------------------------------------ clients

@lru_cache(maxsize=1)
def admin():
    """Supabase service-role client (Supabase backend only)."""
    from supabase import create_client
    if not (SUPABASE_URL and SUPABASE_SECRET_KEY):
        raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY must be set in .env.")
    return create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)


@lru_cache(maxsize=1)
def s3():
    """boto3 S3 client. Credentials: AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY from .env."""
    import boto3
    from botocore.config import Config
    if not S3_BUCKET:
        raise RuntimeError("STORAGE_BACKEND=s3 but S3_BUCKET is missing from .env.")
    if not AWS_REGION:
        raise RuntimeError("STORAGE_BACKEND=s3 needs AWS_REGION in .env (the bucket's region, e.g. ap-south-1).")
    # SigV4 + virtual-hosted URLs: required for presigned URLs in every AWS region. A custom
    # endpoint (local/MinIO) uses path-style addressing instead.
    endpoint = S3_ENDPOINT_URL or None
    return boto3.client("s3", region_name=AWS_REGION, endpoint_url=endpoint,
                        config=Config(signature_version="s3v4", s3={"addressing_style": "path" if endpoint else "virtual"},
                                      retries={"max_attempts": 5, "mode": "standard"}))


# Bounded transfers: at most 4 parallel 8 MB parts in flight, so a download or upload of any
# size costs ~32 MB of buffers, not the file size (boto3's default allows 10 × 8 MB).
TRANSFER_CHUNK = 8 * 1024 * 1024


@lru_cache(maxsize=1)
def _transfer_config():
    from boto3.s3.transfer import TransferConfig
    return TransferConfig(multipart_threshold=TRANSFER_CHUNK, multipart_chunksize=TRANSFER_CHUNK,
                          max_concurrency=4, use_threads=True)


def check_ready() -> None:
    """Fail at startup with a clear message instead of on the first upload."""
    if STORAGE_BACKEND == "s3":
        s3().head_bucket(Bucket=S3_BUCKET)
    else:
        admin()


async def storage_ready() -> None:
    """Reach the bucket once at service startup (both APIs) so a bad key, region or bucket
    fails there with a clear message."""
    import asyncio
    try:
        await asyncio.to_thread(check_ready)
    except Exception as e:
        where = f"S3 bucket {S3_BUCKET!r}" if STORAGE_BACKEND == "s3" else "the Supabase bucket"
        raise RuntimeError(f"Can't reach {where}: {type(e).__name__}: {e}. Check the keys, AWS_REGION and the "
                           "bucket name in .env (the key needs s3:ListBucket on the bucket).") from e


def _field(res: Any, *names: str) -> Any:
    for n in names:
        if isinstance(res, dict) and n in res:
            return res[n]
        if hasattr(res, n):
            return getattr(res, n)
    return None


def _absolute(url: str) -> str:
    if url.startswith("http"):
        return url
    if not url.startswith("/"):
        url = "/" + url
    return f"{SUPABASE_URL}/storage/v1{url}"


def _not_found(e: Exception) -> bool:
    code = str(getattr(e, "response", {}).get("Error", {}).get("Code", "")) if hasattr(e, "response") else ""
    return code in ("404", "NoSuchKey", "NotFound")


# ------------------------------------------------------------------ uploads (browser)

def create_signed_upload_url(key: str) -> dict:
    """Short-lived URL the browser uploads the file to (bytes never hit our APIs).
    → {url, token, method}: method "s3-put" (raw body) or "supabase-put" (multipart, token in URL)."""
    if STORAGE_BACKEND == "s3":
        url = s3().generate_presigned_url(
            "put_object", Params={"Bucket": S3_BUCKET, "Key": key}, ExpiresIn=UPLOAD_URL_TTL_SECONDS,
        )
        return {"url": url, "token": "", "method": "s3-put"}
    res = admin().storage.from_(MEDIA_BUCKET).create_signed_upload_url(key)
    token = _field(res, "token")
    url = _field(res, "signedURL", "signed_url", "signedUrl")
    if not url or not token:
        raise RuntimeError(f"Unexpected signed-upload response: {res!r}")
    return {"url": _absolute(str(url)), "token": str(token), "method": "supabase-put"}


# ------------------------------------------------------------------ downloads (browser)

# Signed URLs are reused until 80% of their lifetime has passed. A fresh token on every
# request makes each URL unique, so the browser re-downloads thumbnails/audio it already
# has; a stable URL lets the HTTP cache serve them. Per process, bounded, thread-safe.
_URL_REUSE_FRACTION = 0.8
_URL_CACHE_MAX = 5000
_url_cache: dict[tuple[str, int], tuple[str, float]] = {}
_url_lock = threading.Lock()


def _sign_download(key: str, ttl: int) -> str:
    if STORAGE_BACKEND == "s3":
        return s3().generate_presigned_url("get_object", Params={"Bucket": S3_BUCKET, "Key": key}, ExpiresIn=ttl)
    res = admin().storage.from_(MEDIA_BUCKET).create_signed_url(key, ttl)
    url = _field(res, "signedURL", "signed_url", "signedUrl", "signed_url_with_token")
    if not url:
        raise RuntimeError(f"Unexpected signed-url response: {res!r}")
    return _absolute(str(url))


def create_signed_download_url(key: str, ttl: int = SIGNED_URL_TTL_SECONDS) -> str:
    now = time.monotonic()
    with _url_lock:
        hit = _url_cache.get((key, ttl))
        if hit and hit[1] > now:
            return hit[0]
    url = _sign_download(key, ttl)
    with _url_lock:
        if len(_url_cache) >= _URL_CACHE_MAX:
            for k in [k for k, (_, exp) in _url_cache.items() if exp <= now] or list(_url_cache)[: _URL_CACHE_MAX // 10]:
                _url_cache.pop(k, None)
        _url_cache[(key, ttl)] = (url, now + ttl * _URL_REUSE_FRACTION)
    return url


def forget_signed_urls(keys: list[str]) -> None:
    """Drop cached URLs for objects that were deleted or overwritten."""
    gone = set(keys)
    with _url_lock:
        for k in [k for k in _url_cache if k[0] in gone]:
            _url_cache.pop(k, None)


# ------------------------------------------------------------------ server-side object access

def object_info(key: str) -> dict | None:
    """Exists/size/content type for one object, or None when it doesn't exist."""
    if STORAGE_BACKEND == "s3":
        try:
            r = s3().head_object(Bucket=S3_BUCKET, Key=key)
        except Exception as e:
            if _not_found(e):
                return None
            raise
        return {"name": key.rpartition("/")[2], "size": int(r["ContentLength"]), "mimetype": r.get("ContentType")}
    folder, _, name = key.rpartition("/")
    entries = admin().storage.from_(MEDIA_BUCKET).list(folder or "") or []
    for e in entries:
        ename = _field(e, "name")
        if ename != name:
            continue
        meta = _field(e, "metadata") or {}
        if not isinstance(meta, dict):
            meta = {}
        size = meta.get("size") or meta.get("contentLength")
        return {"name": ename, "size": int(size) if size is not None else None,
                "mimetype": meta.get("mimetype")}
    return None


def list_folder(prefix: str) -> list[str]:
    """Full keys of the objects directly under `prefix` (no trailing slash)."""
    if STORAGE_BACKEND == "s3":
        keys: list[str] = []
        for page in s3().get_paginator("list_objects_v2").paginate(Bucket=S3_BUCKET, Prefix=f"{prefix}/", Delimiter="/"):
            keys += [o["Key"] for o in page.get("Contents", [])]
        return keys
    entries = admin().storage.from_(MEDIA_BUCKET).list(prefix) or []
    names = [e.get("name") if isinstance(e, dict) else getattr(e, "name", None) for e in entries]
    return [f"{prefix}/{n}" for n in names if n]


def upload_file(local_path: str, key: str, content_type: str) -> None:
    if STORAGE_BACKEND == "s3":
        # Managed transfer: multipart for large files, retries built in. Overwrites like upsert.
        s3().upload_file(local_path, S3_BUCKET, key, ExtraArgs={"ContentType": content_type}, Config=_transfer_config())
        forget_signed_urls([key])
        return
    # Read bytes ourselves (with a short retry) instead of handing the path to
    # storage3: on Windows, Defender briefly locks a freshly-written file
    # (WinError 32), and storage3's open(file, "rb") never closes the handle —
    # which then also breaks TemporaryDirectory cleanup. Bytes are accepted
    # natively and sidestep both problems.
    data = _read_with_retry(local_path)
    # "upsert" must be the STRING "true": storage3 copies the value straight into
    # the x-upsert HTTP header, and httpx rejects non-str/bytes header values.
    admin().storage.from_(MEDIA_BUCKET).upload(
        key, data, {"content-type": content_type, "upsert": "true"}
    )
    forget_signed_urls([key])


def _read_with_retry(local_path: str, tries: int = 5, delay: float = 0.25) -> bytes:
    last: OSError | None = None
    for i in range(tries):
        try:
            with open(local_path, "rb") as f:
                return f.read()
        except OSError as e:
            last = e
            if i < tries - 1:
                time.sleep(delay)
    raise last  # type: ignore[misc]


def download_to(key: str, dst: str) -> int:
    """Stream an object straight to a file and return its size. Workers use this for videos:
    a 500 MB source never sits in RAM (S3 streams in chunks via a managed transfer)."""
    if STORAGE_BACKEND == "s3":
        s3().download_file(S3_BUCKET, key, dst, Config=_transfer_config())
    else:
        # storage3 has no streaming download; write and drop the bytes at once.
        data = download(key)
        with open(dst, "wb") as f:
            f.write(data)
        del data
    import os
    return os.path.getsize(dst)


def download(key: str) -> bytes:
    if STORAGE_BACKEND == "s3":
        return s3().get_object(Bucket=S3_BUCKET, Key=key)["Body"].read()
    return admin().storage.from_(MEDIA_BUCKET).download(key)


def remove(keys: list[str]) -> None:
    if not keys:
        return
    if STORAGE_BACKEND == "s3":
        for i in range(0, len(keys), 1000):          # DeleteObjects takes at most 1000 keys
            batch = keys[i:i + 1000]
            r = s3().delete_objects(Bucket=S3_BUCKET, Delete={"Objects": [{"Key": k} for k in batch], "Quiet": True})
            if r.get("Errors"):
                first = r["Errors"][0]
                raise RuntimeError(f"S3 delete failed for {len(r['Errors'])} object(s), e.g. {first.get('Key')}: {first.get('Message')}")
    else:
        admin().storage.from_(MEDIA_BUCKET).remove(keys)
    forget_signed_urls(keys)
