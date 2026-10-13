"""Speech (Gnani) and language (Gemini) behind one small interface, with offline fakes.

Speech reuses backend/app/providers (GnaniSpeech / FakeSpeech) unchanged. The language side
is new: chunking (D4) and per-chunk translation. Every provider exception is mapped to a
typed EditorError here, so the worker never sees a raw httpx/genai error.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

from .chunking import EMOTION_TAGS, NEUTRAL
from .config import (
    CHUNK_TARGET_MAX_S, CHUNK_TARGET_MIN_S, FAKE_PROVIDERS, GOOGLE_API_KEY, LLM_MODEL, TTS_SR,
)
from .errors import MediaFailed, OutputInvalid, ProviderError, ProviderRejected
from backend.app.media import MediaError
from backend.app.providers.gnani import GnaniError

LANG_NAMES = {
    "hi-IN": "Hindi (Devanagari script)", "en-IN": "Indian English", "ta-IN": "Tamil (Tamil script)",
    "te-IN": "Telugu (Telugu script)", "kn-IN": "Kannada (Kannada script)", "ml-IN": "Malayalam (Malayalam script)",
    "mr-IN": "Marathi (Devanagari script)", "bn-IN": "Bengali (Bengali script)", "gu-IN": "Gujarati (Gujarati script)",
    "pa-IN": "Punjabi (Gurmukhi script)",
    "hi-en": "Hinglish (Hindi with natural English words, written in Roman script)",
}

_STATUS_RE = re.compile(r"Gnani (\d{3})")


def _gnani_error(e: GnaniError) -> Exception:
    m = _STATUS_RE.search(str(e))
    status = int(m.group(1)) if m else None
    if status is not None and 400 <= status < 500 and status != 429:
        return ProviderRejected(f"Gnani rejected the request: {e}")
    return ProviderError(f"Gnani is unavailable: {e}")


class Speech:
    def __init__(self, impl) -> None:
        self.impl = impl

    async def transcribe(self, audio: Path, lang: str) -> dict:
        try:
            return await self.impl.transcribe(audio, lang)
        except httpx.HTTPError as e:
            raise ProviderError(f"Gnani STT network error: {e}") from e
        except MediaError as e:
            raise MediaFailed(f"Couldn't prepare audio for STT: {e}") from e
        except GnaniError as e:
            raise _gnani_error(e) from e

    async def tts(self, text: str, voice: dict, lang: str, speed: float) -> bytes:
        if voice.get("mode") != "persona" or not voice.get("voice_id"):
            raise ProviderRejected(f"Unsupported voice {voice!r}.")
        try:
            audio = await self.impl.tts(text, voice["voice_id"], lang, speed, sr=TTS_SR)
        except httpx.HTTPError as e:
            raise ProviderError(f"Gnani TTS network error: {e}") from e
        except GnaniError as e:
            raise _gnani_error(e) from e
        if not audio or audio[:4] != b"RIFF":
            raise OutputInvalid(f"Gnani TTS returned {len(audio or b'')} bytes that aren't WAV.", "tts_invalid")
        return audio


# ------------------------------------------------------------------ language

CHUNK_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "emotion_tag": {"type": "string", "enum": [NEUTRAL, *EMOTION_TAGS]},
        },
        "required": ["text", "emotion_tag"],
    },
}

TRANSLATE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {"id": {"type": "integer"}, "text": {"type": "string"}},
        "required": ["id", "text"],
    },
}


def chunk_prompt(text: str, lang: str) -> str:
    return f"""Cut this spoken {LANG_NAMES.get(lang, lang)} text into chunks for a text-to-speech voice,
so that it sounds human: each chunk is one natural breath group, usually one sentence,
about {CHUNK_TARGET_MIN_S:.0f}-{CHUNK_TARGET_MAX_S:.0f} seconds when spoken. Cut where the emotion or delivery changes.

For each chunk give the emotion_tag that best fits how it should be spoken, from this list only:
{NEUTRAL}, {", ".join(EMOTION_TAGS)}. Most chunks are "{NEUTRAL}"; don't over-label.

STRICT RULES:
- Copy the text exactly. Do not change, translate, correct, add or remove any character.
- The chunks, in order, must together contain the whole text and nothing else.
Return JSON only.

Text:
{text}"""


def translate_prompt(items: list[dict], src: str, tgt: str) -> str:
    return f"""Translate each spoken line from {LANG_NAMES.get(src, src)} into {LANG_NAMES.get(tgt, tgt)} for a voice-over.
Spoken register, not written. Keep names, numbers, brands and technical words. Write numbers as digits.
Return one item per input id, same ids, JSON only.

Lines:
{json.dumps(items, ensure_ascii=False)}"""


class GeminiLanguage:
    def __init__(self) -> None:
        from google import genai
        self.client = genai.Client(api_key=GOOGLE_API_KEY)

    async def _json(self, prompt: str, schema: dict) -> object:
        from google.genai import errors as gerrors
        from google.genai import types
        try:
            r = await self.client.aio.models.generate_content(
                model=LLM_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.2, response_mime_type="application/json", response_json_schema=schema,
                ),
            )
        except gerrors.APIError as e:
            if e.code == 429 or (e.code or 500) >= 500:
                raise ProviderError(f"Gemini is unavailable ({e.code}): {e.message}") from e
            raise ProviderRejected(f"Gemini rejected the request ({e.code}): {e.message}") from e
        except httpx.HTTPError as e:
            raise ProviderError(f"Gemini network error: {e}") from e
        try:
            return json.loads(r.text or "")
        except json.JSONDecodeError as e:
            raise OutputInvalid(f"Gemini returned non-JSON output: {(r.text or '')[:200]!r}") from e

    async def chunk(self, text: str, lang: str) -> object:
        return await self._json(chunk_prompt(text, lang), CHUNK_SCHEMA)

    async def translate(self, items: list[dict], src: str, tgt: str) -> object:
        return await self._json(translate_prompt(items, src, tgt), TRANSLATE_SCHEMA)


class FakeLanguage:
    """Deterministic, offline: sentence cuts; a tag when the text obviously implies one."""

    _SENT = re.compile(r"[^.!?।]+[.!?।]*")

    async def chunk(self, text: str, lang: str) -> object:
        out = []
        for m in self._SENT.finditer(text):
            s = m.group(0).strip()
            if not s:
                continue
            low = s.lower()
            tag = "laugh" if "haha" in low else "sigh" if "uff" in low else NEUTRAL
            out.append({"text": s, "emotion_tag": tag})
        return out

    async def translate(self, items: list[dict], src: str, tgt: str) -> object:
        return [{"id": it["id"], "text": f"[{tgt}] {it['text']}"} for it in items]


def validate_translation(items: list[dict], raw: object) -> dict[int, str]:
    if not isinstance(raw, list):
        raise OutputInvalid("Translation returned no list.", "translation_invalid")
    want = {it["id"] for it in items}
    got: dict[int, str] = {}
    for r in raw:
        if not isinstance(r, dict) or not isinstance(r.get("id"), int) or not isinstance(r.get("text"), str):
            raise OutputInvalid(f"Malformed translation item {r!r}"[:200], "translation_invalid")
        if not r["text"].strip():
            raise OutputInvalid(f"Empty translation for line {r['id']}.", "translation_invalid")
        got[r["id"]] = " ".join(r["text"].split())
    if set(got) != want:
        missing, extra = sorted(want - set(got)), sorted(set(got) - want)
        raise OutputInvalid(f"Translation ids don't match (missing {missing}, extra {extra}).", "translation_invalid")
    return got


def get() -> tuple[Speech, object]:
    if FAKE_PROVIDERS:
        from backend.app.providers.fake import FakeSpeech
        return Speech(FakeSpeech()), FakeLanguage()
    from backend.app.providers.gnani import GnaniSpeech
    return Speech(GnaniSpeech()), GeminiLanguage()
