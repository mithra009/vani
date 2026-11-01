"""Gnani Prisma v2.5 (Batch STT), Timbre v2.5 (TTS) and voice-clone TTS over REST.
Request shapes follow docs.gnani.ai (STTBatch/*, TTS/tts-inference, VC/*)."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from pathlib import Path

import httpx

from ..config import GNANI_API_KEY, GNANI_BASE

log = logging.getLogger("vani.gnani")

TERMINAL = {"COMPLETED", "PARTIAL_FAILURE", "FAILED", "START_FAILED", "CANCELLED"}
POLL_S = 10            # docs: poll no faster than every 10 s
AUTO_LANGS = "hi-IN,en-IN"   # language identification over up to 3 codes


# Timbre v3.0: the only model that performs audio tags (v2.5 strips them before synthesis).
# 13 voices, each speaks every language. docs.gnani.ai/api/TTS/tts-inference, /available-voices.
TTS_MODEL = "timbre-v3.0"
V3_TAGS = frozenset({"coughs", "excited", "exhales", "giggle", "laugh", "pauses", "shouting", "sigh", "slow",
                     "sniffles", "whispers", "yawns", "clears throat"})
# Older tags (still produced by the dubbing pipeline, and stored on earlier chunks) → nearest v3 tag, or dropped.
_LEGACY_TAGS = {"chuckle": "giggle", "laughs harder": "laugh", "softly": "whispers", "high-pitched": "excited",
                "rushed": "excited", "long_pause": "pauses", "stammers": None}
_TAG_RE = re.compile(r"<([a-z _-]+)>\s?")

# v2.5 voices on earlier projects → a v3 voice of the same gender, so those projects keep working.
_V25_MALE = {"Deepak", "Dhruva", "Girish", "Hemraj", "Ishaan", "Jalaj", "Kavin", "Omkar", "Pranav", "Riyaan",
             "Roopesh", "Shlok", "Veera", "Vikrant", "Zayan"}
_V25_FEMALE = {"Ambuja", "Asmita", "Bhavna", "Brinda", "Chitra", "Devika", "Falak", "Jwala", "Kaveri", "Kirra",
               "Lavanya", "Lehara", "Mehuli", "Nalini", "Noopur", "Poorvi", "Reshma", "Saanvi", "Suhana", "Trisha",
               "Trupti", "Urmila", "Varuni", "Vedika", "Yashvi", "Yukti", "Zahira"}
V3_VOICE_FOR = {**{v: "Yashraj" for v in _V25_MALE}, **{v: "Lakshmi" for v in _V25_FEMALE}}


def v3_tags(text: str) -> str:
    """Rewrite audio tags to ones Timbre v3 performs; unknown tags are dropped, never spoken aloud."""
    def sub(m: re.Match) -> str:
        tag = m.group(1)
        tag = tag if tag in V3_TAGS else _LEGACY_TAGS.get(tag)
        return f"<{tag}> " if tag else ""
    return _TAG_RE.sub(sub, text)


class GnaniError(RuntimeError):
    pass


class GnaniSpeech:
    def __init__(self) -> None:
        if not GNANI_API_KEY:
            raise GnaniError("GNANI_API_KEY is missing from .env.")
        self.h = {"X-API-Key-ID": GNANI_API_KEY}

    async def _req(self, method: str, url: str, **kw) -> httpx.Response:
        """Retry 429 and 5xx with exponential backoff and jitter (PLAN C12)."""
        for attempt in range(4):
            async with httpx.AsyncClient(timeout=httpx.Timeout(120, connect=20)) as c:
                r = await c.request(method, url, headers={**self.h, **kw.pop("headers", {})}, **kw)
            if r.status_code < 400:
                return r
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 3:
                await asyncio.sleep(2 ** attempt + random.random())
                continue
            raise GnaniError(f"Gnani {r.status_code} on {url.rsplit('/', 2)[-2:]}: {r.text[:300]}")
        raise GnaniError("unreachable")

    # ---------- STT (Batch) ----------
    async def transcribe(self, audio: Path, lang: str, diarize: bool = False, num_speakers: int | None = None,
                         on_progress=None) -> dict:
        config = {
            "model": "gnani-prisma-v2.5",
            "language_code": AUTO_LANGS if lang == "auto" else lang,
            "mode": "transcribe",
            "with_diarization": diarize,
            "with_denoise": True,
            "is_multi_channel": False,
        }
        if diarize and num_speakers:
            config["num_speakers"] = num_speakers
        files = {
            "config": (None, json.dumps(config), "application/json"),
            "files": (audio.name, audio.read_bytes(), "audio/ogg"),
        }
        r = await self._req("POST", f"{GNANI_BASE}/stt/v3/batch/jobs", files=files)
        job_id = r.json()["job_id"]
        await self._req("POST", f"{GNANI_BASE}/stt/v3/batch/jobs/{job_id}/start")

        waited = 0
        while True:
            await asyncio.sleep(POLL_S)
            waited += POLL_S
            st = (await self._req("GET", f"{GNANI_BASE}/stt/v3/batch/jobs/{job_id}")).json()
            if on_progress:
                on_progress(min(0.95, waited / 90))
            if st["status"] in TERMINAL:
                break
            if waited > 1800:
                raise GnaniError("Batch STT took over 30 minutes.")
        if st["status"] != "COMPLETED":
            raise GnaniError(f"Batch STT ended as {st['status']}.")

        files_r = (await self._req("GET", f"{GNANI_BASE}/stt/v3/batch/jobs/{job_id}/files")).json()
        item = files_r["data"][0]
        async with httpx.AsyncClient(timeout=60) as c:
            tr = (await c.get(item["transcript_url"])).json()
        return {
            "language": tr.get("language_code") or (None if lang == "auto" else lang),
            "segments": [
                {"start_s": float(s["start_time"]), "end_s": float(s["end_time"]),
                 "text": s.get("text", ""), "speaker": s.get("speaker_id")}
                for s in tr.get("segments", [])
            ],
            "gnani_job_id": job_id,
        }

    # ---------- TTS ----------
    @staticmethod
    def _audio_config(sr: int) -> dict:
        return {"sample_rate": sr, "num_channels": 1, "sample_width": 2, "encoding": "linear_pcm", "container": "wav"}

    async def tts(self, text: str, voice: str, lang: str, speed: float = 1.0, sr: int = 48000) -> bytes:
        # Gnani is ALWAYS asked for normal speed. Its speed setting re-performs the line (a different
        # take, not the same one faster) and isn't reliably faster, so callers change speed afterwards
        # with ffmpeg atempo on this 1.0 take. `speed` is accepted for the call signature and ignored.
        body = {
            "text": v3_tags(text), "model": TTS_MODEL, "voice": V3_VOICE_FOR.get(voice, voice), "language": lang,
            "speed": 1.0, "audio_config": self._audio_config(sr),
        }
        r = await self._req("POST", f"{GNANI_BASE}/api/v1/tts/inference", json=body)
        return r.content

    # ---------- Voice clone ----------
    async def clone_embedding(self, ref_wav: Path) -> dict:
        files = {"audio_file": (ref_wav.name, ref_wav.read_bytes(), "audio/wav")}
        r = await self._req("POST", f"{GNANI_BASE}/api/v1/tts/voice-clone/embeddings", files=files)
        data = r.json()
        if not data.get("success", True):
            raise GnaniError(f"Voice clone failed: {data.get('message')}")
        return data["data"]["voice_clone_embedding"]

    async def clone_tts(self, text: str, embedding: dict, lang: str, speed: float, sr: int = 48000) -> bytes:
        # The documented clone request has no language or speed field; speed is applied
        # afterwards with atempo by the fit engine.
        body = {"text": text, "speaker_embedding": embedding, "audio_config": self._audio_config(sr)}
        r = await self._req("POST", f"{GNANI_BASE}/api/v1/tts/inference", json=body)
        return r.content
