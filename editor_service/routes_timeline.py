"""Editor endpoints, phase 2 (alignment / timeline). Design §7, §10.

    GET    /api/editor/projects/{id}/timeline                 {version, doc, media}
    POST   /api/editor/projects/{id}/timeline/ops             {base_version, ops[]} → {version, doc}; 409 carries current
    POST   /api/editor/projects/{id}/media/init               music upload (C11-proposal: per project)
    POST   /api/editor/projects/{id}/media/{mid}/complete
    GET    /api/editor/projects/{id}/media/{mid}/url
    POST   /api/editor/projects/{id}/chunks/{cid}/split       If-Match: <revision>; {at_char}   (C4: regenerates)
    POST   /api/editor/projects/{id}/chunks/merge             {first_id, first_revision, second_id, second_revision}
    GET    /api/editor/projects/{id}/overlaps                 lines that run into the next one
    POST   /api/editor/projects/{id}/overlaps/fix             {mode: speed | shorten} → re-voices those lines
"""

from __future__ import annotations

import asyncio
from pathlib import PurePosixPath
from uuid import UUID

from fastapi import APIRouter, Header, Request
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from media_service import storage
from media_service.auth import User
from . import db, overlaps, providers, ratelimit, timeline
from .errors import Conflict, InputInvalid, LimitReached, OutputInvalid
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


# ------------------------------------------------------------------ overlaps (user-requested fixes)

class FixOverlaps(BaseModel):
    mode: Literal["speed", "shorten"]


async def _overlapping(p, pid: str, owner: str) -> tuple[list[dict], dict[str, dict]]:
    tl = await db.get_timeline(p, pid, owner, timeline.default_doc)
    chunks = await db.list_chunks(p, pid, owner)
    return overlaps.overlapping(tl["doc"], chunks), {str(c["id"]): c for c in chunks}


@router.get("/projects/{project_id}/overlaps")
async def list_overlaps(request: Request, project_id: UUID, user: User):
    p, pid, owner = pool(request), str(project_id), user["id"]
    await db.get_project(p, pid, owner)
    lines, _ = await _overlapping(p, pid, owner)
    return [{"chunk_id": x["chunk_id"], "length_s": x["length_s"], "available_s": x["available_s"],
             "speed": x["speed"], "speed_to_fit": overlaps.speed_to_fit(x)} for x in lines]


@router.post("/projects/{project_id}/overlaps/fix")
async def fix_overlaps(request: Request, project_id: UUID, user: User, body: FixOverlaps):
    """Re-voice every line that runs into the next one: faster (exact, computed) or shorter (Gemini)."""
    p, pid, owner = pool(request), str(project_id), user["id"]
    project = await db.get_project(p, pid, owner)
    if project["status"] != "editing":
        raise Conflict("Wait until every line has its voice, then fix overlaps.")
    lines, by_id = await _overlapping(p, pid, owner)
    fixed, skipped = [], []
    if body.mode == "speed":
        for x in lines:
            s = overlaps.speed_to_fit(x)
            if s is None:
                skipped.append({"chunk_id": x["chunk_id"], "reason": f"needs more than {overlaps.MAX_SPEED:g}× to fit"})
                continue
            c = by_id[x["chunk_id"]]
            await db.edit_chunk(p, pid, owner, x["chunk_id"], c["revision"], {"speed": s})
            fixed.append({"chunk_id": x["chunk_id"], "speed": s})
        return {"fixed": fixed, "skipped": skipped}

    if not lines:
        return {"fixed": [], "skipped": []}
    items = [{"id": n, "text": x["text"], "original": x["source_text"], "audio_ms": round(x["length_s"] * 1000),
              "available_ms": round(x["available_s"] * 1000), "max_chars": overlaps.shorten_budget(x)}
             for n, x in enumerate(lines)]
    try:
        await ratelimit.acquire(p, "gemini", owner)
    except ratelimit.Throttled as e:
        raise LimitReached(f"Gemini is busy right now; try again in {e.delay_s:.0f} s.")
    _, llm = providers.get()
    try:
        got = providers.validate_translation(items, await llm.shorten(items, project["tgt_lang"]))
    except OutputInvalid as e:
        raise OutputInvalid(f"Gemini couldn't shorten the lines: {e}", "shorten_invalid")
    for it, x in zip(items, lines):
        text = got[it["id"]]
        if len(text) > it["max_chars"] * 1.15 or len(text) >= len(x["text"]):
            skipped.append({"chunk_id": x["chunk_id"], "reason": "Gemini's shorter version was still too long"})
            continue
        c = by_id[x["chunk_id"]]
        await db.edit_chunk(p, pid, owner, x["chunk_id"], c["revision"], {"text": text})
        fixed.append({"chunk_id": x["chunk_id"], "text": text})
    return {"fixed": fixed, "skipped": skipped}
