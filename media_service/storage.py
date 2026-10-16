"""Supabase Storage helpers (service-role client, server-side only).

Signed URLs are short-lived and never stored in the database. supabase-py returns
relative paths like "/object/sign/media/...?token=..." for some calls, so every
URL is normalized to an absolute one here.
"""

from __future__ import annotations

import logging
import threading
import time
from functools import lru_cache
from typing import Any

from supabase import Client, create_client

from .config import MEDIA_BUCKET, SUPABASE_SECRET_KEY, SUPABASE_URL, SIGNED_URL_TTL_SECONDS

log = logging.getLogger("media.storage")


@lru_cache(maxsize=1)
def admin() -> Client:
    if not (SUPABASE_URL and SUPABASE_SECRET_KEY):
        raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY must be set in .env.")
    return create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)


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


def create_signed_upload_url(key: str) -> dict:
    """Short-lived URL + token the browser POSTs the file to (bytes never hit our APIs)."""
    res = admin().storage.from_(MEDIA_BUCKET).create_signed_upload_url(key)
    token = _field(res, "token")
    url = _field(res, "signedURL", "signed_url", "signedUrl")
    if not url or not token:
        raise RuntimeError(f"Unexpected signed-upload response: {res!r}")
    return {"url": _absolute(str(url)), "token": str(token)}


# Signed URLs are reused until 80% of their lifetime has passed. A fresh token on every
# request makes each URL unique, so the browser re-downloads thumbnails/audio it already
# has; a stable URL lets the HTTP cache serve them. Per process, bounded, thread-safe.
_URL_REUSE_FRACTION = 0.8
_URL_CACHE_MAX = 5000
_url_cache: dict[tuple[str, int], tuple[str, float]] = {}
_url_lock = threading.Lock()


def create_signed_download_url(key: str, ttl: int = SIGNED_URL_TTL_SECONDS) -> str:
    now = time.monotonic()
    with _url_lock:
        hit = _url_cache.get((key, ttl))
        if hit and hit[1] > now:
            return hit[0]
    res = admin().storage.from_(MEDIA_BUCKET).create_signed_url(key, ttl)
    url = _field(res, "signedURL", "signed_url", "signedUrl", "signed_url_with_token")
    if not url:
        raise RuntimeError(f"Unexpected signed-url response: {res!r}")
    url = _absolute(str(url))
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


def object_info(key: str) -> dict | None:
    """Exists/size/metadata for one object, or None. Uses list() on the parent folder."""
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


def upload_file(local_path: str, key: str, content_type: str) -> None:
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


def download(key: str) -> bytes:
    return admin().storage.from_(MEDIA_BUCKET).download(key)


def remove(keys: list[str]) -> None:
    if keys:
        admin().storage.from_(MEDIA_BUCKET).remove(keys)
        forget_signed_urls(keys)
