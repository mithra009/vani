"""Content-addressed keys: the same inputs always map to the same artifact, so a
cached result is reused and nothing is paid for twice (design §6.3)."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

STT_MODEL = "gnani-prisma-v2.5"
TTS_MODEL = "timbre-v2.5"


def h(*parts) -> str:
    raw = json.dumps(parts, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def file_hash(p: Path) -> str:
    d = hashlib.sha256()
    with open(p, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            d.update(block)
    return d.hexdigest()


def speed_str(speed: float | Decimal) -> str:
    # 1.0, 1.000 and Decimal("1.000") must hash identically.
    return f"{float(speed):.3f}"


def stt_key(audio_hash: str, lang: str) -> str:
    return h("stt", STT_MODEL, audio_hash, lang)


def tts_key(text: str, voice: dict, lang: str, emotion_tag: str, speed: float | Decimal) -> str:
    return h("tts", TTS_MODEL, text, voice, lang, emotion_tag, speed_str(speed))


def artifact_path(owner_id: str, kind: str, key: str, ext: str) -> str:
    return f"{owner_id}/artifacts/{kind}/{key}.{ext}"
