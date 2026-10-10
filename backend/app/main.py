"""HTTP API used by the React frontend (contract: frontend/src/lib/api.js, PLAN.md §6).

    .venv\\Scripts\\python -m uvicorn backend.app.main:app --port 8010
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from . import jobs, media, pipeline, providers, store
from .auth import User, me_router, router as auth_router
from .config import FAKE_PROVIDERS, MAX_UPLOAD_BYTES, MAX_VIDEO_SECONDS

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("vani.api")

EDITABLE = {"src_text", "emotion", "emotion_overridden", "keep_original"}
PREVIEW_TEXT = {
    "hi-IN": "नमस्ते! यह मेरी आवाज़ है। क्या आपको पसंद आई?",
    "en-IN": "Hello! This is how I sound. Hope you like it.",
    "hi-en": "Hello doston! Yeh meri awaaz hai, kaisi lagi?",
    "ta-IN": "வணக்கம்! இது என் குரல். உங்களுக்குப் பிடித்ததா?",
    "te-IN": "నమస్కారం! ఇది నా గొంతు. మీకు నచ్చిందా?",
    "kn-IN": "ನಮಸ್ಕಾರ! ಇದು ನನ್ನ ಧ್ವನಿ. ನಿಮಗೆ ಇಷ್ಟವಾಯಿತೇ?",
    "ml-IN": "നമസ്കാരം! ഇതാണ് എന്റെ ശബ്ദം. ഇഷ്ടപ്പെട്ടോ?",
    "mr-IN": "नमस्कार! हा माझा आवाज आहे. आवडला का?",
    "bn-IN": "নমস্কার! এটা আমার কণ্ঠ। ভালো লাগল?",
    "gu-IN": "નમસ્તે! આ મારો અવાજ છે. ગમ્યો?",
    "pa-IN": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ! ਇਹ ਮੇਰੀ ਆਵਾਜ਼ ਹੈ। ਪਸੰਦ ਆਈ?",
}


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(jobs.worker())
    await asyncio.sleep(0)
    # Resume work interrupted by a restart; cached paid calls make this free (PLAN N6).
    global DB_ERROR
    try:
        for j in await asyncio.to_thread(store.list_jobs):
            if j["status"] == "transcribing" and (j["mode"] == "dub" or j.get("narration")):
                jobs.enqueue(pipeline.transcribe, j["id"])
            elif j["status"] == "dubbing":
                jobs.enqueue(pipeline.dub, j["id"])
        DB_ERROR = None
    except Exception as e:
        DB_ERROR = ("Database tables are missing. Run supabase/migrations/001_users_uploads_projects.sql "
                    "in Supabase → SQL Editor, then restart." if "PGRST205" in str(e) else f"Database error: {e}")
        log.error(DB_ERROR)
    log.info("Vani backend ready (%s providers)", "FAKE" if FAKE_PROVIDERS else "real")
    yield
    store.flush_now()
    task.cancel()


app = FastAPI(title="Vani", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(me_router)


def get_job(job_id: str, user: dict) -> dict:
    job = store.load_job(job_id)
    # Someone else's project looks exactly like a missing one.
    if not job or job.get("user_id") != user["id"]:
        raise HTTPException(404, "This project doesn't exist.")
    return job


async def save_upload(f: UploadFile, dst: Path, limit: int) -> int:
    size = 0
    with open(dst, "wb") as out:
        while chunk := await f.read(1 << 20):
            size += len(chunk)
            if size > limit:
                out.close()
                dst.unlink(missing_ok=True)
                raise HTTPException(413, f"That file is over {limit // 1_000_000} MB.")
            out.write(chunk)
    return size


DB_ERROR: str | None = None


@app.get("/api/health")
def health():
    return {"ok": DB_ERROR is None, "providers": "fake" if FAKE_PROVIDERS else "real", "db_error": DB_ERROR}


@app.get("/api/jobs")
def list_jobs(user: User):
    return [jobs.public({k: v for k, v in j.items() if k != "segments"}) for j in store.list_jobs(user["id"])]


@app.post("/api/jobs")
async def create_job(user: User, video: UploadFile = File(...), src_lang: str = Form("auto"),
                     tgt_lang: str = Form(...), mode: str = Form("dub")):
    if mode not in ("dub", "narrate"):
        raise HTTPException(400, "mode must be 'dub' or 'narrate'.")
    if tgt_lang == "same" and mode != "narrate":
        raise HTTPException(400, "Choose a target language.")
    job_id = uuid.uuid4().hex[:12]
    d = store.job_dir(job_id)
    ext = Path(video.filename or "video.mp4").suffix or ".mp4"
    path = d / f"input{ext}"
    size = await save_upload(video, path, MAX_UPLOAD_BYTES)
    try:
        info = await asyncio.to_thread(media.probe, path)
    except media.MediaError:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, "That file couldn't be read as a video.")
    if not info["has_video"]:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, "That file has no video stream.")
    if mode == "dub" and not info["has_audio"]:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, "That video has no sound to dub. Use \"Narrate it yourself\" instead.")
    if info["duration"] > MAX_VIDEO_SECONDS + 1:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, "That video is longer than 10 minutes.")

    upload_id = await asyncio.to_thread(store.record_upload, user["id"], "video", video.filename or "video",
                                        size, round(info["duration"], 3), str(path))
    job = {
        "id": job_id, "user_id": user["id"], "upload_id": upload_id, "name": video.filename or "video", "size": size, "created_at": int(time.time() * 1000),
        "mode": mode, "status": "awaiting_narration" if mode == "narrate" else "transcribing",
        "stage": None, "stage_progress": 0, "src_lang": src_lang, "tgt_lang": tgt_lang,
        "duration_s": round(info["duration"], 3), "video_url": f"/api/jobs/{job_id}/video",
        "output_url": None, "narration": None, "segments": [], "voice": None, "bg_mode": "duck",
        "stats": None, "error": None,
        "_": {"video_path": str(path), "has_audio": info["has_audio"]},
    }
    store.save_job(job)
    if mode == "dub":
        jobs.enqueue(pipeline.transcribe, job_id)
    return jobs.public(job)


@app.get("/api/jobs/{job_id}")
def read_job(job_id: str, user: User):
    return jobs.public(get_job(job_id, user))


@app.post("/api/jobs/{job_id}/narration")
async def upload_narration(job_id: str, user: User, audio: UploadFile = File(...), offset_s: float = Form(0.0)):
    job = get_job(job_id, user)
    if job["mode"] != "narrate" or job["status"] not in ("awaiting_narration", "review", "failed"):
        raise HTTPException(409, "This project isn't waiting for a narration.")
    d = store.job_dir(job_id)
    raw = d / f"narration_raw{Path(audio.filename or '').suffix or '.webm'}"
    await save_upload(audio, raw, 100_000_000)
    try:
        info = await asyncio.to_thread(media.probe, raw)
    except media.MediaError:
        raise HTTPException(400, "That recording couldn't be read as audio.")
    offset = max(0.0, min(float(offset_s), job["duration_s"] - 0.5))
    length = min(info["duration"], job["duration_s"] - offset)
    if length < 1.0:
        raise HTTPException(400, "The narration is too short.")
    await asyncio.to_thread(store.record_upload, user["id"], "narration", audio.filename or "narration",
                            raw.stat().st_size, round(info["duration"], 3), str(raw))
    wav = d / "narration.wav"
    await asyncio.to_thread(media.ffmpeg, "-i", str(raw), "-t", f"{length:.3f}", "-ac", "1", "-ar", "48000", str(wav))
    job["_"]["narration_path"] = str(wav)
    jobs.update(job, status="transcribing", narration={
        "url": f"/api/jobs/{job_id}/narration.wav", "offset_s": round(offset, 3), "duration_s": round(length, 3)})
    jobs.enqueue(pipeline.transcribe, job_id)
    return jobs.public(job)


@app.patch("/api/jobs/{job_id}/segments")
async def edit_segments(job_id: str, user: User, request: Request):
    job = get_job(job_id, user)
    if job["status"] != "review":
        raise HTTPException(409, "The transcript can only be edited before dubbing.")
    body = await request.json()
    edits = {s["idx"]: s for s in body.get("segments", [])}
    for s in job["segments"]:
        e = edits.get(s["idx"])
        if e:
            s.update({k: e[k] for k in EDITABLE if k in e})
    jobs.update(job)
    return jobs.public(job)


@app.post("/api/jobs/{job_id}/dub")
async def start_dub(job_id: str, user: User, request: Request):
    job = get_job(job_id, user)
    if job["status"] not in ("review", "done", "failed"):
        raise HTTPException(409, "This project isn't ready to dub.")
    if request.headers.get("content-type", "").startswith("multipart/"):
        form = await request.form()
        settings = json.loads(form["settings"])
        sample: UploadFile = form["voice_sample"]
        d = store.job_dir(job_id)
        p = d / "voice_sample.bin"
        await save_upload(sample, p, 20_000_000)
        dur = (await asyncio.to_thread(media.probe, p))["duration"]
        if not 4.5 <= dur <= 31:
            raise HTTPException(400, f"The voice sample is {dur:.1f} s. It needs to be 5 to 30 seconds.")
        job["_"]["voice_sample_path"] = str(p)
        await asyncio.to_thread(store.record_upload, user["id"], "voice_sample", sample.filename or "voice-sample",
                                p.stat().st_size, round(dur, 3), str(p))
    else:
        settings = await request.json()
    voice = settings.get("voice") or {}
    if voice.get("mode") not in ("persona", "clone", "own"):
        raise HTTPException(400, "Choose a voice.")
    if voice["mode"] == "persona" and not voice.get("voice_id"):
        raise HTTPException(400, "Choose a voice.")
    if voice["mode"] == "clone" and not voice.get("consent"):
        raise HTTPException(400, "Voice cloning needs the speaker's consent.")
    if voice["mode"] == "own" and (job["mode"] != "narrate" or job["tgt_lang"] != job["src_lang"]):
        raise HTTPException(400, "Your own recording can only be used for a same-language narration.")
    voice.pop("sample", None)
    jobs.update(job, voice=voice, bg_mode=settings.get("bg_mode", "duck"), status="dubbing", stage=None)
    jobs.enqueue(pipeline.dub, job_id)
    return jobs.public(job)


@app.post("/api/jobs/{job_id}/segments/{idx}/regenerate")
async def regenerate(job_id: str, user: User, idx: int):
    job = get_job(job_id, user)
    if job["status"] != "done" or not 0 <= idx < len(job["segments"]):
        raise HTTPException(409, "That line can't be regenerated now.")
    job = await pipeline.regenerate(job_id, idx)
    return jobs.public(job)


@app.get("/api/jobs/{job_id}/events")
async def events(job_id: str, user: User, request: Request):
    get_job(job_id, user)
    q = jobs.subscribe(job_id)

    async def stream():
        try:
            yield f"data: {json.dumps(jobs.public(get_job(job_id, user)), ensure_ascii=False)}\n\n"
            while not await request.is_disconnected():
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            jobs.unsubscribe(job_id, q)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


def _file(job_id: str, name: str, media_type: str, download: str | None = None) -> FileResponse:
    p = store.job_dir(job_id) / name
    if not p.exists():
        raise HTTPException(404, "Not ready yet.")
    return FileResponse(p, media_type=media_type, filename=download)


@app.get("/api/jobs/{job_id}/video")
def video(job_id: str, user: User):
    return FileResponse(get_job(job_id, user)["_"]["video_path"])


@app.get("/api/jobs/{job_id}/narration.wav")
def narration(job_id: str, user: User):
    get_job(job_id, user)
    return _file(job_id, "narration.wav", "audio/wav")


@app.get("/api/jobs/{job_id}/output.mp4")
def output(job_id: str, user: User):
    job = get_job(job_id, user)
    stem = Path(job["name"]).stem
    return _file(job_id, "output.mp4", "video/mp4", f"{stem}.{job['tgt_lang']}.mp4")


@app.get("/api/jobs/{job_id}/subs.{which}.srt")
def subs(job_id: str, user: User, which: str):
    if which not in ("source", "target"):
        raise HTTPException(404)
    get_job(job_id, user)
    return _file(job_id, f"subs.{which}.srt", "text/plain; charset=utf-8")


@app.get("/api/voices/{voice_id}/preview")
async def voice_preview(voice_id: str, lang: str, user: User):
    """One TTS call per voice and language, ever (cached)."""
    text = PREVIEW_TEXT.get(lang)
    if not text:
        raise HTTPException(400, "Unknown language.")
    path = pipeline.CACHE_DIR / f"preview_{voice_id}_{lang}.wav"
    if not path.exists():
        speech, _ = providers.get()
        path.write_bytes(await speech.tts(text, voice_id, lang, 1.0))
    return FileResponse(path, media_type="audio/wav")
