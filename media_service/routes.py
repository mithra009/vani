"""Media library endpoints (contract consumed by frontend/src/lib/libraryStore.js).

    POST   /api/uploads/init
    POST   /api/uploads/{asset_id}/complete
    GET    /api/assets
    GET    /api/assets/{asset_id}
    GET    /api/assets/{asset_id}/preview-url
    DELETE /api/assets/{asset_id}
"""

from __future__ import annotations

import logging

import asyncpg
from fastapi import APIRouter, HTTPException, Request

from . import db, storage, validators
from .auth import User
from .config import MEDIA_BUCKET, SIGNED_URL_TTL_SECONDS
from .validators import ValidationError

log = logging.getLogger("media.routes")
router = APIRouter(prefix="/api")


def pool(request: Request) -> asyncpg.Pool:
    return request.app.state.pool


def derivative_keys(storage_key: str) -> tuple[str, str]:
    prefix = storage_key.rsplit("/", 1)[0]
    return f"{prefix}/thumb.jpg", f"{prefix}/proxy.mp4"


def public(a: dict, thumbnail_url: str | None = None) -> dict:
    return {
        "id": str(a["id"]),
        "projectId": a.get("project_id"),
        "original_filename": a["original_filename"],
        "storage_key": a["storage_key"],
        "size_bytes": a["size_bytes"],
        "duration_ms": a["duration_ms"],
        "status": a["status"],
        "metadata_status": a["metadata_status"],
        "thumbnail_status": a["thumbnail_status"],
        "proxy_status": a["proxy_status"],
        "metadata": a.get("metadata"),
        "created_at": a["created_at"].isoformat() if a.get("created_at") else None,
        "thumbnail_url": thumbnail_url,
    }


def _thumb_url(a: dict) -> str | None:
    if a.get("thumbnail_status") != "READY":
        return None
    try:
        key, _ = derivative_keys(a["storage_key"])
        return storage.create_signed_download_url(key, SIGNED_URL_TTL_SECONDS)
    except Exception as e:  # never fail the whole listing over a signed URL
        log.warning("thumbnail signed url failed for %s: %s", a.get("id"), e)
        return None


@router.post("/uploads/init")
async def init_upload(request: Request, user: User, body: dict):
    try:
        fields = validators.validate_init(
            body.get("original_filename"), body.get("size_bytes"), body.get("duration_ms")
        )
    except ValidationError as e:
        raise HTTPException(400, str(e))

    p = pool(request)
    count, total = await db.quota(p, user["id"])
    try:
        validators.check_quota(count, total, fields["size_bytes"])
    except ValidationError as e:
        raise HTTPException(400, str(e))

    asset_id = validators.new_asset_id()
    key = validators.build_storage_key(user["id"], asset_id, fields["original_filename"])
    asset = await db.create_asset(
        p, user["id"], original_filename=fields["original_filename"], storage_key=key,
        size_bytes=fields["size_bytes"], duration_ms=fields["duration_ms"], asset_id=asset_id,
    )
    signed = storage.create_signed_upload_url(key)
    return {
        "assetId": str(asset["id"]),
        "storageKey": key,
        "bucket": MEDIA_BUCKET,
        "uploadUrl": signed["url"],
        "token": signed["token"],
        "asset": public(asset),
    }


@router.post("/uploads/{asset_id}/complete")
async def complete_upload(request: Request, asset_id: str, user: User):
    p = pool(request)
    asset = await db.get_asset(p, asset_id, user["id"])
    if asset is None:
        raise HTTPException(404, "That upload doesn't exist.")

    info = storage.object_info(asset["storage_key"])
    if info is None:
        raise HTTPException(422, "That file hasn't finished uploading to storage.")
    if info.get("size") is not None and int(info["size"]) != int(asset["size_bytes"]):
        raise HTTPException(422, "The uploaded file doesn't match the declared size. Upload it again.")

    try:
        asset = await db.complete_upload(p, asset_id, user["id"], int(info["size"] or asset["size_bytes"]))
    except PermissionError as e:
        raise HTTPException(409, str(e))
    if asset is None:
        raise HTTPException(404, "That upload doesn't exist.")
    return public(asset)


@router.get("/assets")
async def list_assets(request: Request, user: User):
    rows = await db.list_assets(pool(request), user["id"])
    return [public(a, _thumb_url(a)) for a in rows]


@router.get("/assets/{asset_id}")
async def get_asset(request: Request, asset_id: str, user: User):
    asset = await db.get_asset(pool(request), asset_id, user["id"])
    if asset is None:
        raise HTTPException(404, "That video doesn't exist.")
    return public(asset, _thumb_url(asset))


@router.get("/assets/{asset_id}/preview-url")
async def preview_url(request: Request, asset_id: str, user: User):
    asset = await db.get_asset(pool(request), asset_id, user["id"])
    if asset is None:
        raise HTTPException(404, "That video doesn't exist.")
    if asset["proxy_status"] != "READY":
        raise HTTPException(409, "The preview isn't ready yet.")
    _, proxy_key = derivative_keys(asset["storage_key"])
    try:
        url = storage.create_signed_download_url(proxy_key, SIGNED_URL_TTL_SECONDS)
    except Exception as e:
        log.error("proxy signed url failed for %s: %s", asset_id, e)
        raise HTTPException(502, "Couldn't prepare a preview URL. Try again.")
    return {"url": url, "expires_in": SIGNED_URL_TTL_SECONDS}


@router.delete("/assets/{asset_id}")
async def delete_asset(request: Request, asset_id: str, user: User):
    asset = await db.soft_delete(pool(request), asset_id, user["id"])
    if asset is None:
        raise HTTPException(404, "That video doesn't exist.")
    return {"ok": True, "id": asset_id}
