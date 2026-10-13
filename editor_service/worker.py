"""Editor worker: claims editor_jobs (SKIP LOCKED) and runs the generation loop.

    python -m editor_service.worker

export:   one ffmpeg render of a timeline snapshot (phase 3).
generate: extract audio → (clean narration) → STT → Gemini chunk + emotion → translate → place,
          then one `tts` job per chunk (queued in the same transaction as the chunks).
tts:      one chunk's speech, content-addressed so an unchanged chunk is never paid for twice.

No silent failures: every job ends DONE, SKIPPED (with the reason) or FAILED (with a code and
message written to the job *and* to the project or chunk the user is looking at).
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import shutil
import tempfile
import time
from pathlib import Path

import soundfile as sf

from backend.app import media as amedia
from media_service import storage
from . import chunking, db, export, keys, placement, providers
from .config import (
    CHUNK_LLM_ATTEMPTS, DEFAULT_CPS, EXPORT_TIMEOUT_SECONDS, JOB_MAX_ATTEMPTS, MAX_VIDEO_SECONDS, SCRIPT_GAP_S,
    WORKER_POLL_SECONDS, WORKER_REAP_SECONDS, WORKER_STALE_JOB_SECONDS, check_providers,
)
from .errors import EditorError, InputInvalid, MediaFailed, OutputInvalid, Skip, StorageUnavailable

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("editor.worker")


# ------------------------------------------------------------------ storage (patched in tests)

async def download(key: str, dst: Path) -> Path:
    try:
        data = await asyncio.to_thread(storage.download, key)
    except Exception as e:
        raise StorageUnavailable(f"Couldn't read {key} from storage: {type(e).__name__}: {e}") from e
    if not data:
        raise MediaFailed(f"Stored file {key} is empty.")
    dst.write_bytes(data)
    return dst


async def upload_bytes(data: bytes, key: str, content_type: str, workdir: Path) -> None:
    p = workdir / Path(key).name
    p.write_bytes(data)
    try:
        await asyncio.to_thread(storage.upload_file, str(p), key, content_type)
    except Exception as e:
        raise StorageUnavailable(f"Couldn't write {key} to storage: {type(e).__name__}: {e}") from e


async def _ff(fn, *args):
    try:
        return await asyncio.to_thread(fn, *args)
    except amedia.MediaError as e:
        raise MediaFailed(str(e)) from e


# ------------------------------------------------------------------ generate

async def source_audio(pool, project: dict, workdir: Path) -> Path:
    """The audio STT will hear: the video's own track, or the cleaned one-take narration."""
    kind = project["input_kind"]
    if kind == "video_audio":
        src = await download(project["asset_key"], workdir / ("source" + Path(project["asset_key"]).suffix))
        info = await _ff(amedia.probe, src)
        if not info["has_audio"]:
            raise InputInvalid("This video has no audio track to dub. Use a script or narration instead.", "no_audio")
    elif kind == "narration":
        if not project.get("narration_key"):
            raise InputInvalid("The narration recording is missing.", "no_narration")
        raw = await download(project["narration_key"], workdir / ("narration" + Path(project["narration_key"]).suffix))
        src = await _ff(amedia.clean_voice, raw, workdir / "narration_clean.wav")   # R4: denoise + amplify
    else:
        raise ValueError(f"source_audio called for input_kind={kind!r}")
    return await _ff(amedia.to_upload_opus, src, workdir / "stt.ogg")


async def transcribe(pool, speech, project: dict, audio: Path, workdir: Path) -> list[dict]:
    owner = str(project["owner_id"])
    key = keys.stt_key(keys.file_hash(audio), project["src_lang"])
    hit = await db.artifact_get(pool, owner, key)
    if hit:
        f = await download(hit["storage_key"], workdir / "stt.json")
        log.info("stt cache hit %s", key[:12])
        return json.loads(f.read_text(encoding="utf-8"))["segments"]
    result = await speech.transcribe(audio, project["src_lang"])
    skey = keys.artifact_path(owner, "stt_json", key, "json")
    await upload_bytes(json.dumps(result, ensure_ascii=False).encode(), skey, "application/json", workdir)
    await db.artifact_put(pool, owner, key, "stt_json", skey, {"segments": len(result["segments"])})
    return result["segments"]


async def cut_chunks(lang_llm, transcript: chunking.Transcript, lang: str) -> list[chunking.Chunk]:
    """Ask Gemini; validate; retry once on invalid output; then fail with the reason."""
    last: OutputInvalid | None = None
    for attempt in range(1, CHUNK_LLM_ATTEMPTS + 1):
        try:
            return chunking.validate(transcript, await lang_llm.chunk(transcript.text, lang))
        except OutputInvalid as e:
            last = e
            log.warning("chunking attempt %d/%d invalid: %s", attempt, CHUNK_LLM_ATTEMPTS, e)
    raise OutputInvalid(f"Gemini couldn't chunk the text without changing it: {last}", "chunking_invalid")


async def translate(lang_llm, chunks: list[chunking.Chunk], src: str, tgt: str) -> list[str]:
    if src == tgt:
        return [c.text for c in chunks]
    items = [{"id": c.idx, "text": c.text} for c in chunks]
    got = providers.validate_translation(items, await lang_llm.translate(items, src, tgt))
    return [got[c.idx] for c in chunks]


async def handle_generate(pool, job: dict, project: dict, workdir: Path) -> None:
    speech, lang_llm = providers.get()
    duration = float(project["duration_s"]) if project.get("duration_s") is not None else None
    if duration is None or duration <= 0:
        raise InputInvalid("The source video has no known duration yet. Wait for the Library to finish processing.", "asset_not_ready")
    if duration > MAX_VIDEO_SECONDS + 1:
        raise InputInvalid(f"Videos are limited to {MAX_VIDEO_SECONDS // 60} minutes.", "too_long")

    if project["input_kind"] == "script":
        transcript = chunking.script_transcript(project["script_text"] or "")
        if not transcript.text:
            raise InputInvalid("The script is empty.", "empty_script")
    else:
        audio = await source_audio(pool, project, workdir)
        segments = await transcribe(pool, speech, project, audio, workdir)
        transcript = chunking.build_transcript(segments)
        if not transcript.text:
            raise InputInvalid("No speech was found in the audio.", "no_speech")

    chunks = await cut_chunks(lang_llm, transcript, project["src_lang"])
    texts = await translate(lang_llm, chunks, project["src_lang"], project["tgt_lang"])
    anchors = (placement.place_script(chunks, duration, DEFAULT_CPS, SCRIPT_GAP_S)
               if project["input_kind"] == "script" else placement.place_speech(transcript, chunks))

    rows = [{
        "idx": c.idx, "source_text": c.text, "char_start": c.char_start, "char_end": c.char_end,
        "text": t, "anchor_src_s": a.start_s, "anchor_len_s": a.len_s, "overflow": a.overflow,
        "emotion_tag": c.emotion_tag,
    } for c, t, a in zip(chunks, texts, anchors)]
    await db.replace_chunks(pool, job["project_id"], str(project["owner_id"]), rows, duration)
    overflow = sum(r["overflow"] for r in rows)
    log.info("project %s: %d chunks queued for tts (%d past the video end)", job["project_id"], len(rows), overflow)


# ------------------------------------------------------------------ tts

def wav_seconds(data: bytes) -> float:
    try:
        info = sf.info(io.BytesIO(data))
    except RuntimeError as e:
        raise OutputInvalid(f"TTS audio couldn't be read: {e}", "tts_invalid") from e
    if info.frames <= 0:
        raise OutputInvalid("TTS returned silence (0 frames).", "tts_invalid")
    return info.frames / info.samplerate


async def handle_tts(pool, job: dict, project: dict, workdir: Path) -> None:
    chunk = await db.chunk_generating(pool, job["chunk_id"], job["chunk_revision"])
    if chunk is None:
        raise Skip(f"chunk {job['chunk_id']} moved past revision {job['chunk_revision']}")
    owner = str(project["owner_id"])
    voice, lang = project["voice"], project["tgt_lang"]
    key = keys.tts_key(chunk["text"], voice, lang, chunk["emotion_tag"], chunk["speed"])
    hit = await db.artifact_get(pool, owner, key)
    if hit:
        audio_key, seconds = hit["storage_key"], float(hit["meta"]["duration_s"])
    else:
        speech, _ = providers.get()
        data = await speech.tts(chunking.tts_text(chunk["text"], chunk["emotion_tag"]), voice, lang, float(chunk["speed"]))
        seconds = wav_seconds(data)
        audio_key = keys.artifact_path(owner, "chunk_wav", key, "wav")
        await upload_bytes(data, audio_key, "audio/wav", workdir)
        await db.artifact_put(pool, owner, key, "chunk_wav", audio_key, {"duration_s": round(seconds, 3)})
    if not await db.chunk_audio_ready(pool, chunk["id"], job["chunk_revision"], audio_key, round(seconds, 3)):
        raise Skip(f"chunk {chunk['id']} was edited while its audio was generating")


# ------------------------------------------------------------------ export

async def run_ffmpeg(args: list[str], cwd: Path, duration: float, on_progress) -> None:
    """ffmpeg with -progress on stdout. Non-zero exit or timeout → MediaFailed with stderr's tail."""
    proc = await asyncio.create_subprocess_exec(
        amedia_bin("ffmpeg"), *args, cwd=str(cwd),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stderr_task = asyncio.create_task(proc.stderr.read())
    last = 0.0

    async def pump():
        nonlocal last
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").strip()
            if line.startswith("out_time_us=") or line.startswith("out_time_ms="):
                try:
                    done = int(line.split("=", 1)[1]) / 1e6
                except ValueError:
                    continue                                   # "N/A" before the first frame
                if duration > 0 and time.monotonic() - last > 1.0:
                    last = time.monotonic()
                    await on_progress(min(0.99, done / duration))

    try:
        await asyncio.wait_for(asyncio.gather(pump(), proc.wait()), timeout=EXPORT_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise MediaFailed(f"The export took longer than {EXPORT_TIMEOUT_SECONDS // 60} minutes and was stopped.", "export_timeout")
    err = (await stderr_task).decode(errors="replace").strip()
    if proc.returncode != 0:
        raise MediaFailed(f"ffmpeg failed ({proc.returncode}): {err[-800:]}", "export_failed")


def amedia_bin(name: str) -> str:
    return shutil.which(name) or name


async def handle_export(pool, job: dict, project: dict, workdir: Path) -> None:
    ex = await db.get_export(pool, job["export_id"])
    if ex["status"] == "ready":
        raise Skip("export already rendered")
    await db.export_progress(pool, ex["id"], 0.0)
    snap = ex["snapshot"]

    src = await download(project["asset_key"], workdir / ("source" + Path(project["asset_key"]).suffix))
    info = await _ff(amedia.probe, src)
    if not info["has_video"]:
        raise MediaFailed("The source video can't be read.", "source_invalid")
    height = await _ff(source_height, src)

    chunk_paths: dict[str, str] = {}
    for c in snap["chunks"]:
        if c.get("audio_key"):
            p = workdir / f"chunk_{c['id']}.wav"
            await download(c["audio_key"], p)
            chunk_paths[str(c["id"])] = p.name
    media_paths: dict[str, str] = {}
    for m in snap["media"]:
        p = workdir / f"music_{m['id']}{Path(m['storage_key']).suffix}"
        await download(m["storage_key"], p)
        media_paths[str(m["id"])] = p.name

    plan, warnings, caps = export.plan_from_snapshot(
        snap, fmt=ex["format"], height=ex["height"], audio_mix=ex["audio_mix"], source=src.name,
        source_has_audio=info["has_audio"], source_height=height, chunk_paths=chunk_paths, media_paths=media_paths,
    )
    owner = str(project["owner_id"])
    captions_key = None
    if ex["captions"] != "none":
        kind = "srt" if ex["captions"] == "burn" else ex["captions"]
        text = export.captions_file(caps, kind)
        (workdir / f"captions.{kind}").write_text(text, encoding="utf-8")
        if ex["captions"] == "burn":
            plan.burn_captions = "captions.srt"
        else:
            captions_key = f"{owner}/exports/{ex['id']}.{kind}"
            await upload_bytes(text.encode(), captions_key, "application/x-subrip" if kind == "srt" else "text/vtt", workdir)

    out = f"export.{ex['format']}"
    await run_ffmpeg(export.build_args(plan, out), workdir, plan.duration,
                     lambda p: db.export_progress(pool, ex["id"], p))
    probe_out = await _ff(amedia.probe, workdir / out)
    if abs(probe_out["duration"] - plan.duration) > 0.1:
        raise MediaFailed(f"Rendered {probe_out['duration']:.2f}s but the timeline is {plan.duration:.2f}s.", "export_invalid")
    output_key = f"{owner}/exports/{ex['id']}.{ex['format']}"
    try:
        await asyncio.to_thread(storage.upload_file, str(workdir / out), output_key, export.content_type(ex["format"]))
    except Exception as e:
        raise StorageUnavailable(f"Couldn't write {output_key} to storage: {type(e).__name__}: {e}") from e
    await db.export_done(pool, ex["id"], output_key, captions_key, warnings)
    log.info("export %s ready: %s, %.1fs, %d warning(s)", ex["id"], ex["format"], plan.duration, len(warnings))


def source_height(path: Path) -> int:
    out = amedia.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=height",
                      "-of", "csv=p=0", str(path)])
    try:
        return int(out.strip().splitlines()[0])
    except (ValueError, IndexError) as e:
        raise amedia.MediaError(f"Couldn't read the video height: {out!r}") from e


HANDLERS = {"generate": handle_generate, "tts": handle_tts, "export": handle_export}


# ------------------------------------------------------------------ loop

async def record_failure(pool, job: dict, err: EditorError | Exception) -> None:
    code = getattr(err, "code", "internal")
    retry = bool(getattr(err, "retryable", False))
    msg = str(err) if isinstance(err, EditorError) else f"Something went wrong on our side ({type(err).__name__})."
    final = await db.finish_job(pool, job, outcome="FAILED", code=code, error=f"{type(err).__name__}: {err}", retry=retry)
    if not final:
        log.warning("job %s %s failed, will retry (attempt %s/%s): %s", job["id"], job["kind"],
                    job["attempts"], JOB_MAX_ATTEMPTS, err)
        return
    log.error("job %s %s failed permanently [%s]: %s", job["id"], job["kind"], code, err)
    if job["kind"] == "generate":
        await db.fail_project(pool, job["project_id"], code, msg)
    elif job["kind"] == "export":
        await db.export_failed(pool, job["export_id"], code, msg)
    else:
        await db.chunk_failed(pool, job["chunk_id"], job["chunk_revision"], code, msg)


async def process_one(pool) -> bool:
    job = await db.claim_job(pool)
    if job is None:
        return False
    log.info("job %s kind=%s project=%s chunk=%s attempt=%s",
             job["id"], job["kind"], job["project_id"], job.get("chunk_id"), job["attempts"])
    started = time.monotonic()
    try:
        project = await db.project_for_job(pool, job)
        if project is None:
            raise Skip("project deleted")
        with tempfile.TemporaryDirectory(prefix=f"editor-{job['kind']}-", ignore_cleanup_errors=True) as td:
            await HANDLERS[job["kind"]](pool, job, project, Path(td))
        await db.finish_job(pool, job, outcome="DONE")
        log.info("job %s done in %.1fs", job["id"], time.monotonic() - started)
    except Skip as e:
        await db.finish_job(pool, job, outcome="SKIPPED", error=str(e))
        log.info("job %s skipped: %s", job["id"], e)
    except EditorError as e:
        await record_failure(pool, job, e)
    except Exception as e:
        log.exception("job %s crashed", job["id"])
        await record_failure(pool, job, e)
    return True


async def main() -> None:
    check_providers()
    pool = await db.connect()
    try:
        await db.check_schema(pool)
    except RuntimeError as e:
        log.error("%s", e)
        await pool.close()
        raise SystemExit(1)
    log.info("editor worker ready (fake providers: %s)", providers.FAKE_PROVIDERS)
    last_reap = float("-inf")
    errors = 0
    try:
        while True:
            try:
                if time.monotonic() - last_reap >= WORKER_REAP_SECONDS:
                    last_reap = time.monotonic()
                    for j in await db.requeue_stale_jobs(pool, WORKER_STALE_JOB_SECONDS):
                        log.warning("requeued stale job %s kind=%s (attempt %s)", j["id"], j["kind"], j["attempts"])
                worked = await process_one(pool)
                errors = 0
            except Exception:
                # DB unreachable etc. The job (if any) stays RUNNING and the reaper requeues it.
                # Back off so a persistent fault is logged every ~minute, not every poll.
                errors += 1
                if errors <= 3 or errors % 20 == 0:
                    log.exception("worker loop error (%d in a row)", errors)
                await asyncio.sleep(min(60.0, WORKER_POLL_SECONDS * 2 ** min(errors, 7)))
                continue
            if not worked:
                await asyncio.sleep(WORKER_POLL_SECONDS)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
