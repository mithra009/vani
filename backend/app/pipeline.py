"""The dubbing pipeline (PLAN.md §5). Two entry points run on the background worker:
`transcribe(job_id)` → status 'review', and `dub(job_id)` → status 'done'.
Every paid call is cached by content hash, so a re-run after a crash or edit costs nothing."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path

import numpy as np

from . import emotion as emo
from . import fit, media, providers, store
from .config import LLM_MODEL, MIX_SR, STT_SR, TTS_CONCURRENCY
from .jobs import update
from .providers.fake import speech_regions

log = logging.getLogger("vani.pipeline")

CACHE_DIR = store.STORAGE / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
TRANSLATE_BATCH = 20
LABEL_BATCH = 40


def h(*parts) -> str:
    m = hashlib.sha256()
    for p in parts:
        m.update(p if isinstance(p, bytes) else json.dumps(p, sort_keys=True, ensure_ascii=False).encode())
    return m.hexdigest()


def file_hash(p: Path) -> str:
    m = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            m.update(chunk)
    return m.hexdigest()


def progress(job: dict, stage: str, p: float) -> None:
    update(job, stage=stage, stage_progress=round(min(1.0, max(0.0, p)), 3))


# ---------------------------------------------------------------- transcribe

async def transcribe(job_id: str) -> None:
    job = store.load_job(job_id)
    d = store.job_dir(job_id)
    speech, llm = providers.get()
    update(job, status="transcribing", error=None)

    # 1 ingest
    progress(job, "ingest", 0.1)
    video = Path(job["_"]["video_path"])
    if not (d / "orig48.wav").exists() and job["_"]["has_audio"]:
        await asyncio.to_thread(media.extract_audio, video, d / "orig48.wav", MIX_SR)
    if job["mode"] == "narrate":
        src_audio = Path(job["_"]["narration_path"])
        offset = job["narration"]["offset_s"]
        await asyncio.to_thread(media.extract_audio, src_audio, d / "narr16.wav", STT_SR)
        await asyncio.to_thread(media.extract_audio, src_audio, d / "narr48.wav", MIX_SR)
        stt_wav = d / "narr16.wav"
    else:
        offset = 0.0
        await asyncio.to_thread(media.extract_audio, video, d / "src16.wav", STT_SR)
        stt_wav = d / "src16.wav"
    await asyncio.to_thread(media.to_upload_opus, stt_wav, d / "stt.ogg")
    progress(job, "ingest", 1.0)

    # 2 transcribe (cached by audio content + language)
    progress(job, "transcribe", 0.02)
    key = h("stt", file_hash(stt_wav), job["src_lang"])
    result = store.cache_get(key)
    if result is None:
        result = await speech.transcribe(d / "stt.ogg", job["src_lang"],
                                         on_progress=lambda p: progress(job, "transcribe", p))
        store.cache_put(key, "stt", result)
    src_lang = result.get("language") or ("hi-IN" if job["src_lang"] == "auto" else job["src_lang"])
    if src_lang not in fit.DEFAULT_CPS:
        src_lang = src_lang.split(",")[0]
    x16, _ = media.read(stt_wav)
    regions = speech_regions(x16, STT_SR)
    pauses = [(regions[i][1], regions[i + 1][0]) for i in range(len(regions) - 1)]
    segs = fit.normalise(result["segments"], pauses)
    dur = job["duration_s"]
    for s in segs:
        s["start_s"] = round(min(dur, s["start_s"] + offset), 3)
        s["end_s"] = round(min(dur, s["end_s"] + offset), 3)
    segs = [s for s in segs if s["end_s"] - s["start_s"] > 0.2]
    segs = fit.slots(segs, dur)
    progress(job, "transcribe", 1.0)

    # 3 emotion: acoustic features (relative to this speaker) fused with the LLM's text label
    progress(job, "emotion", 0.05)
    feats = []
    for s in segs:
        a, b = int((s["start_s"] - offset) * STT_SR), int((s["end_s"] - offset) * STT_SR)
        feats.append(emo.features(x16[max(0, a): max(a + 1, b)], STT_SR))
    base = emo.baseline(feats) if feats else {}
    labels = await _label_emotions(llm, [s["text"] for s in segs], src_lang)
    fused = [emo.fuse(lab["emotion"], lab["intensity"], emo.arousal(f, base)) for lab, f in zip(labels, feats)]
    fused = emo.smooth(fused)
    progress(job, "emotion", 1.0)

    tgt = src_lang if job["tgt_lang"] == "same" else job["tgt_lang"]
    segments = [{
        "idx": i, "start_s": s["start_s"], "end_s": s["end_s"], "slot_end_s": s["slot_end_s"],
        "speaker": s.get("speaker"), "src_text": s["text"], "tgt_text": "",
        "emotion": e, "intensity": inten, "nonverbal": labels[i].get("nonverbal", []),
        "acoustic": {k: round(v, 3) for k, v in feats[i].items()},
        "emotion_overridden": False, "keep_original": False,
        "speed": None, "stretch": None, "flags": [],
    } for i, (s, (e, inten)) in enumerate(zip(segs, fused))]

    update(job, status="review", stage=None, stage_progress=0, src_lang=src_lang, tgt_lang=tgt, segments=segments)


async def _label_emotions(llm, texts: list[str], lang: str) -> list[dict]:
    out: list[dict] = []
    for i in range(0, len(texts), LABEL_BATCH):
        batch = [{"id": i + k, "text": t} for k, t in enumerate(texts[i: i + LABEL_BATCH])]
        key = h("emo", LLM_MODEL, lang, batch)
        res = store.cache_get(key)
        if res is None:
            res = await llm.label_emotions(batch, lang)
            store.cache_put(key, "emotion", res)
        by_id = {r["id"]: r for r in res}
        for b in batch:
            r = by_id.get(b["id"], {})
            out.append({"emotion": r.get("emotion", "neutral"), "intensity": int(r.get("intensity", 1)),
                        "nonverbal": r.get("nonverbal", [])})
    return out


# ---------------------------------------------------------------- dub

async def dub(job_id: str) -> None:
    job = store.load_job(job_id)
    d = store.job_dir(job_id)
    speech, llm = providers.get()
    update(job, status="dubbing", error=None, stage=None, stats=None)
    voice = job["voice"]
    dur = job["duration_s"]

    if voice["mode"] == "own":
        progress(job, "clean", 0.2)
        await asyncio.to_thread(media.clean_voice, d / "narr48.wav", d / "narr_clean.wav")
        progress(job, "clean", 1.0)
        progress(job, "assemble", 0.3)
        x, _ = media.read(d / "narr_clean.wav")
        tl = np.zeros(int(round(dur * MIX_SR)), dtype=np.float32)
        media.place(tl, media.fade(x, MIX_SR), job["narration"]["offset_s"], MIX_SR)
        media.write(d / "voice.wav", tl, MIX_SR)
        for s in job["segments"]:
            s["tgt_text"], s["speed"], s["stretch"], s["flags"] = s["src_text"], 1.0, 1.0, []
        progress(job, "assemble", 1.0)
        await _finish(job, d, label_ai=False)
        return

    src, tgt = job["src_lang"], job["tgt_lang"]
    segs = job["segments"]
    voice_key = voice.get("voice_id") or "clone"
    cps = store.voice_cps(voice_key, tgt) or fit.DEFAULT_CPS.get(tgt, 13.0)

    # translate
    if tgt != src:
        progress(job, "translate", 0.05)
        await _translate(llm, job, segs, src, tgt, cps)
    else:
        for s in segs:
            tags, _ = emo.controls(s["emotion"], s["intensity"])
            lead = "".join(f"<{t}> " for t in tags)
            tail = "".join(f" <{n}>" for n in s.get("nonverbal", [])[:1])
            s["tgt_natural"] = s["tgt_short"] = f"{lead}{s['src_text']}{tail}".strip()
    progress(job, "translate", 1.0)

    # clone embedding
    embedding = None
    if voice["mode"] == "clone":
        ref = d / "clone_ref.wav"
        if voice.get("source") == "video":
            base = d / ("narr16.wav" if job["mode"] == "narrate" else "src16.wav")
            off = job["narration"]["offset_s"] if job["mode"] == "narrate" else 0.0
            r = voice["reference"]
            await asyncio.to_thread(media.cut, base, ref, max(0, r["start_s"] - off), max(0.1, r["end_s"] - off))
        else:
            await asyncio.to_thread(media.extract_audio, Path(job["_"]["voice_sample_path"]), ref, STT_SR)
        key = h("clone", file_hash(ref))
        embedding = store.cache_get(key)
        if embedding is None:
            embedding = await speech.clone_embedding(ref)
            store.cache_put(key, "clone", embedding)

    # synthesise + fit
    todo = [s for s in segs if not s["keep_original"]]
    done = 0
    sem = asyncio.Semaphore(TTS_CONCURRENCY)

    async def one(s: dict) -> None:
        nonlocal done
        async with sem:
            await _synth_fit(speech, job, d, s, segs, voice, embedding, tgt, cps)
        done += 1
        progress(job, "synthesize", done / max(1, len(todo)))

    progress(job, "synthesize", 0.0)
    await asyncio.gather(*(one(s) for s in todo))
    progress(job, "fit", 1.0)

    # assemble
    progress(job, "assemble", 0.2)
    await asyncio.to_thread(_assemble, job, d)
    progress(job, "assemble", 1.0)
    await _finish(job, d, label_ai=voice["mode"] == "clone")


async def _translate(llm, job: dict, segs: list[dict], src: str, tgt: str, cps: float) -> None:
    for i in range(0, len(segs), TRANSLATE_BATCH):
        chunk = segs[i: i + TRANSLATE_BATCH]
        items = []
        for s in chunk:
            if s["keep_original"]:
                continue
            k = s["idx"]
            tags, _ = emo.controls(s["emotion"], s["intensity"])
            items.append({
                "id": k, "text": s["src_text"],
                "context_before": segs[k - 1]["src_text"] if k > 0 else "",
                "context_after": segs[k + 1]["src_text"] if k + 1 < len(segs) else "",
                "emotion": s["emotion"], "intensity": s["intensity"],
                "nonverbal": s.get("nonverbal", []),
                "budget": fit.char_budget(s["slot_end_s"] - s["start_s"], cps),
                "tags": tags + s.get("nonverbal", [])[:1],
            })
        if not items:
            continue
        key = h("tr", LLM_MODEL, src, tgt, items)
        res = store.cache_get(key)
        if res is None:
            res = await llm.translate(items, src, tgt)
            store.cache_put(key, "translate", res)
        by_id = {r["id"]: r for r in res}
        for it in items:
            r = by_id.get(it["id"]) or {"natural": it["text"], "short": it["text"]}
            s = segs[it["id"]]
            allowed = set(it["tags"])
            clean = lambda t: fit.TAG_RE.sub(lambda m: m.group(0) if m.group(1).strip() in allowed else "", t).strip()
            s["tgt_natural"], s["tgt_short"] = clean(r["natural"]), clean(r.get("short") or r["natural"])
        progress(job, "translate", (i + len(chunk)) / len(segs))


async def _tts(speech, text: str, voice: dict, embedding, lang: str, speed: float) -> Path:
    if voice["mode"] == "clone":
        key = h("ctts", text, embedding, lang)
    else:
        key = h("tts", text, voice["voice_id"], lang, round(speed, 3))
    path = CACHE_DIR / f"{key}.wav"
    if not path.exists():
        if voice["mode"] == "clone":
            data = await speech.clone_tts(text, embedding, lang, speed)
        else:
            data = await speech.tts(text, voice["voice_id"], lang, speed)
        path.write_bytes(data)
    return path


async def _synth_fit(speech, job, d: Path, s: dict, segs: list[dict], voice: dict, embedding, tgt: str, cps: float,
                     force_short: bool = False) -> None:
    slot = s["slot_end_s"] - s["start_s"]
    k = s["idx"]
    next_start = segs[k + 1]["start_s"] if k + 1 < len(segs) else job["duration_s"]
    gap = max(0.0, next_start - s["slot_end_s"])
    _, emo_speed = emo.controls(s["emotion"], s["intensity"])
    clone = voice["mode"] == "clone"

    async def attempt(text: str):
        speed = 1.0 if clone else fit.choose_speed(fit.predict_seconds(text, cps), slot, emo_speed)
        wav = await _tts(speech, text, voice, embedding, tgt, speed)
        x, _ = await asyncio.to_thread(media.read, wav, MIX_SR)
        x = media.trim_silence(x, MIX_SR)
        actual = len(x) / MIX_SR
        speech_s = actual - fit.tag_seconds(text)
        if speech_s > 0.3 and fit.spoken_chars(text) > 8:
            store.record_voice_cps(voice.get("voice_id") or "clone", tgt, fit.spoken_chars(text) * speed / speech_s)
        return text, speed, x, actual

    first = s["tgt_short"] if force_short else s["tgt_natural"]
    text, speed, x, actual = await attempt(first)
    decision = fit.decide(actual, slot, gap, speed, tried_short=force_short)
    if decision.action == "retry_short" and s["tgt_short"] and s["tgt_short"] != s["tgt_natural"]:
        text, speed, x, actual = await attempt(s["tgt_short"])
        decision = fit.decide(actual, slot, gap, speed, tried_short=True)
    elif decision.action == "retry_short":
        decision = fit.decide(actual, slot, gap, speed, tried_short=True)

    stretch = decision.stretch if decision.action in ("stretch", "borrow", "flag") else 1.0
    if clone and actual < slot * 0.8 and emo_speed < 1:
        stretch = max(emo_speed, actual / slot)     # let sad/tender lines breathe a little
    if abs(stretch - 1) > 0.005:
        x = await asyncio.to_thread(media.atempo, x, MIX_SR, stretch, d)
    clip = d / f"seg_{k:04d}.wav"
    media.write(clip, media.fade(x, MIX_SR), MIX_SR)
    s.update(tgt_text=text, speed=speed, stretch=round(stretch, 3),
             flags=["stretched_over_limit"] if decision.action == "flag" else [],
             fitted_s=round(len(x) / MIX_SR, 3), clip=str(clip))


def _assemble(job: dict, d: Path) -> None:
    n = int(round(job["duration_s"] * MIX_SR))
    tl = np.zeros(n, dtype=np.float32)
    orig = None
    if job["bg_mode"] == "mute" and (d / "orig48.wav").exists():
        orig, _ = media.read(d / "orig48.wav")
    for s in job["segments"]:
        if s["keep_original"]:
            if orig is not None:
                a, b = int(s["start_s"] * MIX_SR), int(s["end_s"] * MIX_SR)
                media.place(tl, media.fade(orig[a:b], MIX_SR), s["start_s"], MIX_SR)
            s["tgt_text"] = s["src_text"]
            continue
        x, _ = media.read(Path(s["clip"]))
        media.place(tl, x, s["start_s"], MIX_SR)
    media.write(d / "voice_raw.wav", tl, MIX_SR)
    media.loudnorm(d / "voice_raw.wav", d / "voice_norm.wav")
    # loudnorm can shift length by a few samples; pin it back to the exact timeline length
    y, _ = media.read(d / "voice_norm.wav")
    y = np.pad(y, (0, max(0, n - len(y))))[:n]
    media.write(d / "voice.wav", y, MIX_SR)


async def _finish(job: dict, d: Path, label_ai: bool) -> None:
    progress(job, "mux", 0.3)
    out = d / "output.mp4"
    await asyncio.to_thread(media.mix_and_mux, Path(job["_"]["video_path"]), d / "voice.wav", out,
                            job["bg_mode"], job["duration_s"], label_ai)
    (d / "subs.source.srt").write_text(media.srt(job["segments"], "src_text"), encoding="utf-8")
    (d / "subs.target.srt").write_text(media.srt(job["segments"], "tgt_text"), encoding="utf-8")
    out_dur = media.probe(out)["duration"]
    voiced = [s for s in job["segments"] if not s["keep_original"]]
    pace = sorted((s.get("speed") or 1) * (s.get("stretch") or 1) for s in voiced) or [1.0]
    stats = {
        "segments": len(voiced),
        "flagged": sum(1 for s in voiced if s.get("flags")),
        "stretch_p95": round(pace[min(len(pace) - 1, int(len(pace) * 0.95))], 3),
        "duration_error_samples": int(round(abs(out_dur - job["duration_s"]) * MIX_SR)),
    }
    update(job, status="done", stage=None, stage_progress=1, output_url=f"/api/jobs/{job['id']}/output.mp4", stats=stats)


async def regenerate(job_id: str, idx: int) -> dict:
    """Redo one line with the short translation, then rebuild the soundtrack."""
    job = store.load_job(job_id)
    d = store.job_dir(job_id)
    speech, _ = providers.get()
    s = job["segments"][idx]
    voice = job["voice"]
    embedding = None
    if voice["mode"] == "clone":
        embedding = store.cache_get(h("clone", file_hash(d / "clone_ref.wav")))
    tgt = job["tgt_lang"]
    cps = store.voice_cps(voice.get("voice_id") or "clone", tgt) or fit.DEFAULT_CPS.get(tgt, 13.0)
    await _synth_fit(speech, job, d, s, job["segments"], voice, embedding, tgt, cps, force_short=True)
    await asyncio.to_thread(_assemble, job, d)
    await _finish(job, d, label_ai=voice["mode"] == "clone")
    return job
