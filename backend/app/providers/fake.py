"""Local stand-ins for Gnani and Gemini (FAKE_PROVIDERS=1): free, deterministic, offline.
STT finds real speech regions in the audio by energy, so timing logic is exercised on real
timestamps; TTS returns a tone whose length follows the text, so fitting is exercised too."""

from __future__ import annotations

import io
import re
from pathlib import Path

import numpy as np
import soundfile as sf

from ..fit import DEFAULT_CPS, TAG_RE, tag_seconds
from ..media import read

SAMPLE_LINES = [
    "Namaste doston, aaj main aapko ek bahut interesting cheez dikhane wala hoon.",
    "Pichle hafte maine socha, kyun na apni videos ko har bhasha mein bana doon?",
    "Aur sach bataun, result dekh ke main khud shocked ho gaya, haha!",
    "Lekin ek problem thi, awaaz aur video ka timing match hi nahi ho raha tha.",
    "Teen din tak main bas yahi theek karta raha, uff.",
    "Phir ek idea aaya, har line ko uske apne time pe rakho.",
]


def speech_regions(x: np.ndarray, sr: int, thresh_db: float = -35.0, min_gap: float = 0.35, min_len: float = 0.4):
    win = int(sr * 0.02)
    n = len(x) // win
    if n == 0:
        return []
    db = 20 * np.log10(np.sqrt((x[: n * win].reshape(n, win) ** 2).mean(axis=1)) + 1e-9)
    on = db > max(thresh_db, np.percentile(db, 95) - 30)
    regions, start = [], None
    for i, v in enumerate(on):
        t = i * win / sr
        if v and start is None:
            start = t
        elif not v and start is not None:
            regions.append([start, t])
            start = None
    if start is not None:
        regions.append([start, n * win / sr])
    merged = []
    for r in regions:
        if merged and r[0] - merged[-1][1] < min_gap:
            merged[-1][1] = r[1]
        else:
            merged.append(r)
    return [(a, b) for a, b in merged if b - a >= min_len]


class FakeSpeech:
    async def transcribe(self, audio: Path, lang: str, diarize: bool = False, num_speakers=None, on_progress=None) -> dict:
        wav = audio.with_suffix(".fake.wav")
        from ..media import ffmpeg
        ffmpeg("-i", str(audio), "-ac", "1", "-ar", "16000", str(wav))
        x, sr = read(wav)
        segs = []
        for i, (a, b) in enumerate(speech_regions(x, sr)):
            base = SAMPLE_LINES[i % len(SAMPLE_LINES)]
            n = max(8, int((b - a) * 13))
            text = (base * 3)[:n].rsplit(" ", 1)[0] if len(base) > n else base
            segs.append({"start_s": round(a, 2), "end_s": round(b, 2), "text": text, "speaker": 1})
        return {"language": "hi-IN" if lang == "auto" else lang, "segments": segs, "gnani_job_id": "fake"}

    @staticmethod
    def _tone(text: str, lang: str, speed: float, sr: int, pitch: float) -> bytes:
        cps = DEFAULT_CPS.get(lang, 13.0)
        spoken = len(TAG_RE.sub("", text).strip())
        dur = spoken / (cps * speed) + tag_seconds(text)
        t = np.arange(int(dur * sr)) / sr
        voice = 0.25 * np.sin(2 * np.pi * pitch * t) * (0.6 + 0.4 * np.sin(2 * np.pi * 4 * t) ** 2)
        pad = np.zeros(int(0.15 * sr), dtype=np.float32)
        y = np.concatenate([pad, voice.astype(np.float32), pad])
        buf = io.BytesIO()
        sf.write(buf, y, sr, format="WAV", subtype="PCM_16")
        return buf.getvalue()

    async def tts(self, text: str, voice: str, lang: str, speed: float, sr: int = 48000) -> bytes:
        return self._tone(text, lang, speed, sr, 180 + (sum(map(ord, voice)) % 80))

    async def clone_embedding(self, ref_wav: Path) -> dict:
        return {"embedding": "fake", "shape": [1, 768], "dtype": "torch.bfloat16"}

    async def clone_tts(self, text: str, embedding: dict, lang: str, speed: float, sr: int = 48000) -> bytes:
        return self._tone(text, lang, 1.0, sr, 140)


class FakeLLM:
    async def translate(self, items: list[dict], src: str, tgt: str) -> list[dict]:
        out = []
        for it in items:
            tags = "".join(f"<{t}> " for t in it.get("tags", []))
            text = it["text"]
            short = text[: max(4, int(it["budget"] * 0.8))].rsplit(" ", 1)[0]
            out.append({"id": it["id"], "natural": f"{tags}{text}", "short": f"{tags}{short}"})
        return out

    async def label_emotions(self, lines: list[dict], lang: str) -> list[dict]:
        out = []
        for ln in lines:
            t = ln["text"].lower()
            emo, inten, nv = "neutral", 1, []
            if re.search(r"haha|shocked|!", t):
                emo, inten = "excited", 2
            if "haha" in t:
                nv = ["laugh"]
            if "uff" in t:
                emo, inten, nv = "sad", 2, ["sigh"]
            out.append({"id": ln["id"], "emotion": emo, "intensity": inten, "nonverbal": nv})
        return out
