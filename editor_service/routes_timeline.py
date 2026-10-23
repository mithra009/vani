"""Editor endpoints, phase 2 (alignment / timeline). Design §7, §10.

    GET    /api/editor/projects/{id}/timeline                 {version, doc, media}
    POST   /api/editor/projects/{id}/timeline/ops             {base_version, ops[]} → {version, doc}; 409 carries current
    POST   /api/editor/projects/{id}/media/init               music upload (C11-proposal: per project)
    POST   /api/editor/projects/{id}/media/{mid}/complete
    GET    /api/editor/projects/{id}/media/{mid}/url
    POST   /api/editor/projects/{id}/chunks/{cid}/split       If-Match: <revision>; {at_char}   (C4: regenerates)
    POST   /api/editor/projects/{id}/chunks/merge             {first_id, first_revision, second_id, second_revision}
"""

from __future__ import annotations

import asyncio
from pathlib import PurePosixPath
from uuid import UUID

from fastapi import APIRouter, Header, Request
from pydantic import BaseModel, Field, field_validator

from media_service import storage
from media_service.auth import User
from . import db, timeline
from .errors import InputInvalid
from .routes import _json, _revision, pool, public_chunk

router = APIRouter(prefix="/api/editor")

MUSIC_EXTS = {"mp3", "wav", "m4a", "aac", "ogg", "flac"}
MAX_MUSIC_BYTES = 50_000_000
MAX_OPS_PER_BATCH = 200


def public_media(m: dict) -> dict:
    return {k: _json(v) for k, v in m.items() if k not in {"owner_id", "storage_key"}}


class OpsBatch(BaseModel):
    base_version: int = Field(ge=1)
    ops: list[dict] = Field(min_length=1, max_length=MAX_OPS_PER_BATCH)


class MediaInit(BaseModel):
    filename: str = Field(min_length=1, max_length=200)
    duration_s: float = Field(gt=0, le=3600)     # measured by the browser; export re-probes

    @field_validator("filename")
    @classmethod
    def _ext(cls, v: str) -> str:
        if PurePosixPath(v).suffix.lower().lstrip(".") not in MUSIC_EXTS:
            raise ValueError(f"Audio must be one of {sorted(MUSIC_EXTS)}.")
        return v


class Split(BaseModel):
    at_char: int = Field(ge=1)


class Merge(BaseModel):
    first_id: UUID
    first_revision: int
    second_id: UUID
    second_revision: int


# ------------------------------------------------------------------ timeline

@router.get("/projects/{project_id}/timeline")
async def read_timeline(request: Request, project_id: UUID, user: User):
    p, pid = pool(request), str(project_id)
    tl = await db.get_timeline(p, pid, user["id"], timeline.default_doc)
    media = await db.list_media(p, pid, user["id"])
    return {**tl, "media": [public_media(m) for m in media]}


@router.post("/projects/{project_id}/timeline/ops")
async def timeline_ops(request: Request, project_id: UUID, user: User, body: OpsBatch):
    p, pid, owner = pool(request), str(project_id), user["id"]
    project = await db.get_project(p, pid, owner)
    source_s = float(project["duration_s"] or 0)

    async def apply_fn(conn, doc):
        chunk_ids = {str(c["id"]) for c in await db.list_chunks(conn, pid, owner)}
        media = {str(m["id"]): float(m["duration_s"]) for m in await db.list_media(conn, pid, owner)}
        new_doc, _ = timeline.apply_all(doc, body.ops, source_s=source_s, chunk_ids=chunk_ids, media=media)
        return new_doc, body.ops

    return await db.save_timeline(p, pid, owner, body.base_version, apply_fn, timeline.default_doc)


# ------------------------------------------------------------------ music media

@router.post("/projects/{project_id}/media/init", status_code=201)
async def media_init(request: Request, project_id: UUID, user: User, body: MediaInit):
    ext = PurePosixPath(body.filename).suffix.lower().lstrip(".")
    m = await db.media_init(pool(request), str(project_id), user["id"], body.filename, ext, body.duration_s)
    signed = await asyncio.to_thread(storage.create_signed_upload_url, m["storage_key"])
    return {"media": public_media(m), "uploadUrl": signed["url"], "token": signed["token"],
            "uploadMethod": signed.get("method", "supabase-put"), "storageKey": m["storage_key"]}


@router.post("/projects/{project_id}/media/{media_id}/complete")
async def media_complete(request: Request, project_id: UUID, media_id: UUID, user: User):
    p, pid = pool(request), str(project_id)
    rows = [m for m in await db.list_media(p, pid, user["id"], ready_only=False) if m["id"] == media_id]
    if not rows:
        raise InputInvalid("That audio file doesn't exist.", "not_found")
    info = await asyncio.to_thread(storage.object_info, rows[0]["storage_key"])
    if info is None:
        raise InputInvalid("The audio hasn't finished uploading.", "media_missing")
    if info.get("size") is not None and int(info["size"]) > MAX_MUSIC_BYTES:
        raise InputInvalid("That audio file is too large (50 MB max).", "media_too_large")
    return public_media(await db.media_ready(p, pid, user["id"], str(media_id)))


@router.get("/projects/{project_id}/media/{media_id}/url")
async def media_url(request: Request, project_id: UUID, media_id: UUID, user: User):
    rows = [m for m in await db.list_media(pool(request), str(project_id), user["id"]) if m["id"] == media_id]
    if not rows:
        raise InputInvalid("That audio file doesn't exist.", "not_found")
    return {"url": await asyncio.to_thread(storage.create_signed_download_url, rows[0]["storage_key"])}


# ------------------------------------------------------------------ split / merge

@router.post("/projects/{project_id}/chunks/{chunk_id}/split")
async def split_chunk(request: Request, project_id: UUID, chunk_id: UUID, user: User, body: Split,
                      if_match: str | None = Header(default=None)):
    await db.get_project(pool(request), str(project_id), user["id"])
    rows = await db.split_chunk(pool(request), str(project_id), user["id"], str(chunk_id), _revision(if_match), body.at_char)
    return [public_chunk(c) for c in rows]


@router.post("/projects/{project_id}/chunks/merge")
async def merge_chunks(request: Request, project_id: UUID, user: User, body: Merge):
    await db.get_project(pool(request), str(project_id), user["id"])
    c = await db.merge_chunks(pool(request), str(project_id), user["id"], str(body.first_id), body.first_revision,
                              str(body.second_id), body.second_revision)
    return public_chunk(c)
