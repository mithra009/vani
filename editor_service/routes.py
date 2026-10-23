"""Editor endpoints, phase 1 (input → chunked, voiced project). Design §7.

    GET    /api/editor/projects
    POST   /api/editor/projects
    GET    /api/editor/projects/{id}                      project + chunks
    DELETE /api/editor/projects/{id}
    POST   /api/editor/projects/{id}/narration/init       signed upload URL (one take, D12)
    POST   /api/editor/projects/{id}/narration/complete
    POST   /api/editor/projects/{id}/retry                after a failed generate
    PUT    /api/editor/projects/{id}/voice                one voice per project (D8); regenerates all chunks
    POST   /api/editor/projects/{id}/estimate             provider usage, no calls made
    PATCH  /api/editor/projects/{id}/chunks/{cid}         If-Match: <revision>
    POST   /api/editor/projects/{id}/chunks/{cid}/regenerate
    GET    /api/editor/projects/{id}/chunks/{cid}/audio-url
    GET    /api/editor/projects/{id}/events               SSE: snapshot | error | heartbeat

Errors are always {"code": ..., "message": ...} with a matching HTTP status.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Header, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from media_service import storage
from media_service.auth import User
from . import db
from .chunking import ALLOWED
from .config import (
    EVENTS_POLL_SECONDS, MAX_NARRATION_BYTES, MAX_SCRIPT_CHARS, TTS_SPEED_MAX, TTS_SPEED_MIN,
)
from .errors import Conflict, InputInvalid, LimitReached, NotFound
from .config import BUSY_ACTIVE_USERS, MAX_ACTIVE_GENERATIONS, MAX_PROJECTS_PER_USER
from .providers import LANG_NAMES

log = logging.getLogger("editor.routes")
router = APIRouter(prefix="/api/editor")

NARRATION_EXTS = {"webm", "ogg", "wav", "mp3", "m4a"}


def pool(request: Request) -> asyncpg.Pool:
    return request.app.state.pool


def _json(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (UUID,)):
        return str(v)
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def public_project(p: dict) -> dict:
    hidden = {"owner_id", "deleted_at", "asset_key", "narration_key"}
    out = {k: _json(v) for k, v in p.items() if k not in hidden}
    out["has_narration"] = bool(p.get("narration_key"))
    return out


def public_chunk(c: dict) -> dict:
    return {k: _json(v) for k, v in c.items() if k not in {"owner_id", "audio_key"}} | {"has_audio": bool(c.get("audio_key"))}


# ------------------------------------------------------------------ bodies

class Voice(BaseModel):
    mode: Literal["persona"]          # clone (C15) arrives with voice_profiles; rejected until then
    voice_id: str = Field(min_length=1, max_length=80)


def _check_lang(v: str) -> str:
    if v not in LANG_NAMES:
        raise ValueError(f"Unsupported language {v!r}.")
    return v


class CreateProject(BaseModel):
    asset_id: UUID
    name: str = Field(min_length=1, max_length=120)
    input_kind: Literal["video_audio", "script", "narration"]
    script_text: str | None = Field(default=None, max_length=MAX_SCRIPT_CHARS)
    src_lang: str
    tgt_lang: str
    voice: Voice

    @field_validator("src_lang", "tgt_lang")
    @classmethod
    def _langs(cls, v: str) -> str:
        return _check_lang(v)

    @model_validator(mode="after")
    def _script(self):
        if self.input_kind == "script" and not (self.script_text or "").strip():
            raise ValueError("A script project needs script_text.")
        if self.input_kind != "script" and self.script_text is not None:
            raise ValueError("script_text is only for script projects.")
        return self


class NarrationInit(BaseModel):
    ext: str

    @field_validator("ext")
    @classmethod
    def _ext(cls, v: str) -> str:
        v = v.lower().lstrip(".")
        if v not in NARRATION_EXTS:
            raise ValueError(f"Narration must be one of {sorted(NARRATION_EXTS)}.")
        return v


class SetVoice(BaseModel):
    voice: Voice
    settings_version: int


class EditChunk(BaseModel):
    text: str | None = Field(default=None, min_length=1, max_length=2000)
    emotion_tag: str | None = None
    speed: float | None = Field(default=None, ge=TTS_SPEED_MIN, le=TTS_SPEED_MAX)

    @field_validator("emotion_tag")
    @classmethod
    def _tag(cls, v):
        if v is not None and v not in ALLOWED:
            raise ValueError(f"Unsupported emotion tag {v!r}.")
        return v

    @field_validator("text")
    @classmethod
    def _text(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Text can't be blank.")
        return " ".join(v.split()) if v is not None else v


# ------------------------------------------------------------------ projects

@router.get("/projects")
async def list_projects(request: Request, user: User):
    return [public_project(p) for p in await db.list_projects(pool(request), user["id"])]


def generation_cap(active_users: int) -> int:
    """Projects one user may generate at once: MAX_ACTIVE_GENERATIONS when the app is quiet,
    stepping down linearly to 1 once BUSY_ACTIVE_USERS people are working."""
    if active_users <= 1:
        return MAX_ACTIVE_GENERATIONS
    if active_users >= BUSY_ACTIVE_USERS:
        return 1
    span = (MAX_ACTIVE_GENERATIONS - 1) * (BUSY_ACTIVE_USERS - active_users) / (BUSY_ACTIVE_USERS - 1)
    return max(1, round(1 + span))


async def check_user_limits(p, owner_id: str, *, new_project: bool) -> None:
    n = await db.user_counts(p, owner_id)
    if new_project and n["projects"] >= MAX_PROJECTS_PER_USER:
        raise LimitReached(f"You've reached {MAX_PROJECTS_PER_USER} projects. Delete one to start another.")
    cap = generation_cap(n["active_users"])
    if n["generating"] >= cap:
        raise LimitReached(f"You have {n['generating']} project(s) generating; the limit right now is {cap} at a time "
                           "(it adapts to how busy Vani is). Try again when one finishes.")


@router.post("/projects", status_code=201)
async def create_project(request: Request, user: User, body: CreateProject):
    p = pool(request)
    if body.input_kind != "narration":           # narration starts generating only after the take
        await check_user_limits(p, user["id"], new_project=True)
    elif (await db.user_counts(p, user["id"]))["projects"] >= MAX_PROJECTS_PER_USER:
        raise LimitReached(f"You've reached {MAX_PROJECTS_PER_USER} projects. Delete one to start another.")
    asset = await db.asset_for_owner(p, str(body.asset_id), user["id"])
    if asset is None:
        raise NotFound("That video isn't in your Library.")
    if asset["status"] != "READY" or not asset["duration_ms"]:
        raise InputInvalid("That video is still processing. Try again when the Library shows it ready.", "asset_not_ready")
    project = await db.create_project(
        p, user["id"], asset_id=str(body.asset_id), name=body.name.strip(), input_kind=body.input_kind,
        script_text=" ".join(body.script_text.split()) if body.script_text else None,
        src_lang=body.src_lang, tgt_lang=body.tgt_lang, voice=body.voice.model_dump(),
        duration_s=asset["duration_ms"] / 1000,
    )
    return public_project(project)


@router.get("/projects/{project_id}")
async def read_project(request: Request, project_id: UUID, user: User):
    p = pool(request)
    project = await db.get_project(p, str(project_id), user["id"])
    chunks = await db.list_chunks(p, str(project_id), user["id"])
    return {"project": public_project(project), "chunks": [public_chunk(c) for c in chunks]}


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(request: Request, project_id: UUID, user: User):
    await db.soft_delete_project(pool(request), str(project_id), user["id"])


@router.post("/projects/{project_id}/narration/init")
async def narration_init(request: Request, project_id: UUID, user: User, body: NarrationInit):
    project = await db.get_project(pool(request), str(project_id), user["id"])
    if project["status"] != "awaiting_narration":
        raise Conflict("This project isn't waiting for a narration.")
    key = f"{user['id']}/projects/{project_id}/narration.{body.ext}"
    signed = await asyncio.to_thread(storage.create_signed_upload_url, key)
    return {"uploadUrl": signed["url"], "token": signed["token"], "uploadMethod": signed.get("method", "supabase-put"), "storageKey": key}


@router.post("/projects/{project_id}/narration/complete")
async def narration_complete(request: Request, project_id: UUID, user: User, body: NarrationInit):
    key = f"{user['id']}/projects/{project_id}/narration.{body.ext}"
    await check_user_limits(pool(request), user["id"], new_project=False)
    info = await asyncio.to_thread(storage.object_info, key)
    if info is None:
        raise InputInvalid("The narration hasn't finished uploading.", "narration_missing")
    if info.get("size") is not None and int(info["size"]) > MAX_NARRATION_BYTES:
        raise InputInvalid("That narration file is too large.", "narration_too_large")
    return public_project(await db.narration_uploaded(pool(request), str(project_id), user["id"], key))


@router.post("/projects/{project_id}/retry")
async def retry(request: Request, project_id: UUID, user: User):
    return public_project(await db.retry_generate(pool(request), str(project_id), user["id"]))


@router.put("/projects/{project_id}/voice")
async def set_voice(request: Request, project_id: UUID, user: User, body: SetVoice):
    project = await db.set_voice(pool(request), str(project_id), user["id"], body.voice.model_dump(), body.settings_version)
    return public_project(project)


@router.post("/projects/{project_id}/estimate")
async def estimate(request: Request, project_id: UUID, user: User):
    """Provider usage the next generation would need. Units only; the credit price isn't known here."""
    p = pool(request)
    project = await db.get_project(p, str(project_id), user["id"])
    chunks = await db.list_chunks(p, str(project_id), user["id"])
    pending = [c for c in chunks if c["status"] in ("pending", "failed")]
    needs_generate = not chunks
    return {
        "stt_audio_s": float(project["duration_s"] or 0) if needs_generate and project["input_kind"] != "script" else 0.0,
        "gemini_calls": (1 + (project["src_lang"] != project["tgt_lang"])) if needs_generate else 0,
        "tts_chunks": len(pending),
        "tts_chars": sum(len(c["text"]) for c in pending),
        "note": "Cached chunks with unchanged text, voice, emotion and speed are reused and cost nothing.",
    }


# ------------------------------------------------------------------ chunks

def _revision(if_match: str | None) -> int:
    if not if_match:
        raise InputInvalid("Send the chunk revision in the If-Match header.", "revision_required")
    try:
        return int(if_match.strip().strip('"'))
    except ValueError:
        raise InputInvalid(f"If-Match must be the chunk revision number, got {if_match!r}.", "revision_required")


@router.patch("/projects/{project_id}/chunks/{chunk_id}")
async def edit_chunk(request: Request, project_id: UUID, chunk_id: UUID, user: User, body: EditChunk,
                     if_match: str | None = Header(default=None)):
    changes = body.model_dump(exclude_none=True)
    if not changes:
        raise InputInvalid("Nothing to change.", "empty_edit")
    await db.get_project(pool(request), str(project_id), user["id"])
    c = await db.edit_chunk(pool(request), str(project_id), user["id"], str(chunk_id), _revision(if_match), changes)
    return public_chunk(c)


@router.post("/projects/{project_id}/chunks/{chunk_id}/regenerate")
async def regenerate_chunk(request: Request, project_id: UUID, chunk_id: UUID, user: User):
    await db.get_project(pool(request), str(project_id), user["id"])
    return public_chunk(await db.regenerate_chunk(pool(request), str(project_id), user["id"], str(chunk_id)))


@router.get("/projects/{project_id}/chunks/{chunk_id}/audio-url")
async def chunk_audio_url(request: Request, project_id: UUID, chunk_id: UUID, user: User):
    chunks = await db.list_chunks(pool(request), str(project_id), user["id"])
    c = next((c for c in chunks if c["id"] == chunk_id), None)
    if c is None:
        raise NotFound("That chunk doesn't exist.")
    if not c["audio_key"]:
        raise Conflict("That chunk has no audio yet.")
    url = await asyncio.to_thread(storage.create_signed_download_url, c["audio_key"])
    return {"url": url, "revision": c["revision"]}


# ------------------------------------------------------------------ events

def _sse(event: str, data: object) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=_json)}\n\n"


@router.get("/projects/{project_id}/events")
async def events(request: Request, project_id: UUID, user: User):
    p, pid, owner = pool(request), str(project_id), user["id"]
    await db.get_project(p, pid, owner)   # 404 before the stream opens

    async def stream():
        last, last_beat = None, time.monotonic()
        while not await request.is_disconnected():
            try:
                project = await db.get_project(p, pid, owner)
                chunks = await db.list_chunks(p, pid, owner)
            except NotFound:
                yield _sse("error", {"code": "not_found", "message": "That project was deleted."})
                return
            except Exception as e:
                log.exception("events poll failed for %s", pid)
                yield _sse("error", {"code": "internal", "message": f"Live updates paused: {type(e).__name__}"})
                await asyncio.sleep(EVENTS_POLL_SECONDS * 5)
                continue
            stamp = (project["updated_at"], max((c["updated_at"] for c in chunks), default=None), len(chunks))
            if stamp != last:
                last, last_beat = stamp, time.monotonic()
                yield _sse("snapshot", {"project": public_project(project), "chunks": [public_chunk(c) for c in chunks]})
            elif time.monotonic() - last_beat > 15:
                last_beat = time.monotonic()
                yield _sse("heartbeat", {})
            await asyncio.sleep(EVENTS_POLL_SECONDS)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
