"""Editor endpoints, phase 3 (export). Design §7, §10.5.

    POST /api/editor/projects/{id}/exports                {format, height, audio_mix, captions}
    GET  /api/editor/projects/{id}/exports
    GET  /api/editor/projects/{id}/exports/{eid}/url      signed download URL(s)
"""

from __future__ import annotations

import asyncio
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Request
from pydantic import BaseModel, model_validator

from media_service import storage
from media_service.auth import User
from . import db, keys, timeline
from .errors import Conflict, InputInvalid, NotFound
from .routes import _json, pool

router = APIRouter(prefix="/api/editor")

AUDIO_ONLY = {"mp3", "wav"}


class ExportRequest(BaseModel):
    format: Literal["mp4", "webm", "mov", "mp3", "wav"]
    height: Literal[480, 720, 1080] | None = None
    audio_mix: Literal["full", "voice"] = "full"          # C13-proposal: the user's choice
    captions: Literal["none", "srt", "vtt", "burn"] = "none"

    @model_validator(mode="after")
    def _combo(self):
        if self.format in AUDIO_ONLY:
            if self.height is not None:
                raise ValueError("Audio-only exports have no resolution.")
            if self.captions == "burn":
                raise ValueError("Captions can't be burned into an audio-only export; choose SRT or VTT.")
        elif self.height is None:
            raise ValueError("Choose a resolution: 480, 720 or 1080.")
        return self


def public_export(e: dict) -> dict:
    hidden = {"owner_id", "snapshot", "content_key", "output_key", "captions_key"}
    return {k: _json(v) for k, v in e.items() if k not in hidden} | {
        "has_output": bool(e.get("output_key")), "has_captions": bool(e.get("captions_key"))}


@router.post("/projects/{project_id}/exports", status_code=202)
async def create_export(request: Request, project_id: UUID, user: User, body: ExportRequest):
    p, pid, owner = pool(request), str(project_id), user["id"]
    project = await db.get_project(p, pid, owner)
    if project["status"] != "editing":
        raise Conflict(f"The project is {project['status'].replace('_', ' ')}; export once all audio is generated.")
    tl = await db.get_timeline(p, pid, owner, timeline.default_doc)
    chunks = await db.list_chunks(p, pid, owner)
    media = await db.list_media(p, pid, owner)

    # Everything the editor would play must have current audio; never export a half-finished mix.
    placed, _ = timeline.layout(tl["doc"], [dict(c, id=str(c["id"]), audio_duration_s=c["audio_duration_s"] or 1)
                                            for c in chunks])
    visible = {x.chunk_id for x in placed}
    not_ready = [c for c in chunks if str(c["id"]) in visible and c["status"] != "ready"]
    if not_ready:
        failed = sum(c["status"] == "failed" for c in not_ready)
        raise Conflict(f"{len(not_ready)} chunk(s) aren't ready ({failed} failed). "
                       "Wait for them or regenerate the failed ones, then export.")
    used = {m["media_id"] for m in tl["doc"]["music"]["clips"]}
    missing = used - {str(m["id"]) for m in media}
    if missing:
        raise InputInvalid(f"The timeline uses {len(missing)} audio file(s) that are gone. Remove those clips.", "media_missing")

    snapshot = {
        "doc": tl["doc"],
        "chunks": [{"id": str(c["id"]), "idx": c["idx"], "text": c["text"],
                    "anchor_src_s": _json(c["anchor_src_s"]), "anchor_len_s": _json(c["anchor_len_s"]),
                    "audio_duration_s": _json(c["audio_duration_s"]), "audio_key": c["audio_key"]} for c in chunks],
        "media": [{"id": str(m["id"]), "storage_key": m["storage_key"], "duration_s": _json(m["duration_s"])}
                  for m in media if str(m["id"]) in used],
    }
    content_key = keys.h("export", snapshot, body.format, body.height, body.audio_mix, body.captions)
    e = await db.create_export(p, pid, owner, timeline_version=tl["version"], fmt=body.format, height=body.height,
                               audio_mix=body.audio_mix, captions=body.captions, snapshot=snapshot,
                               content_key=content_key)
    return public_export(e)


@router.get("/projects/{project_id}/exports")
async def list_exports(request: Request, project_id: UUID, user: User):
    await db.get_project(pool(request), str(project_id), user["id"])
    return [public_export(e) for e in await db.list_exports(pool(request), str(project_id), user["id"])]


@router.get("/projects/{project_id}/exports/{export_id}/url")
async def export_url(request: Request, project_id: UUID, export_id: UUID, user: User):
    e = await db.get_export(pool(request), str(export_id), user["id"])
    if str(e["project_id"]) != str(project_id):
        raise NotFound("That export doesn't exist.")
    if e["status"] != "ready" or not e["output_key"]:
        raise Conflict(f"That export is {e['status']}.")
    url = await asyncio.to_thread(storage.create_signed_download_url, e["output_key"])
    cap = await asyncio.to_thread(storage.create_signed_download_url, e["captions_key"]) if e["captions_key"] else None
    return {"url": url, "captions_url": cap}
