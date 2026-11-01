"""Speech (Gnani) and language (Gemini) behind one small interface, with offline fakes.

Speech reuses backend/app/providers (GnaniSpeech / FakeSpeech) unchanged. The language side
is new: chunking (D4) and per-chunk translation. Every provider exception is mapped to a
typed EditorError here, so the worker never sees a raw httpx/genai error.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections import deque
from pathlib import Path

import httpx

from .chunking import EMOTION_TAGS, NEUTRAL
from .config import (
    CHUNK_TARGET_MAX_S, CHUNK_TARGET_MIN_S, FAKE_PROVIDERS, GEMINI_KEY_RPD, GEMINI_KEY_RPM, GEMINI_KEY_TPM,
    GOOGLE_API_KEYS, LLM_MODEL, TTS_SR,
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

log = logging.getLogger("editor.providers")
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
    if tgt == "hi-en":                       # Hinglish is mixed by definition: English words are the point
        words = "Mix Hindi and English the way people naturally speak Hinglish, in Roman script."
    else:
        words = (f"Translate EVERY word into {LANG_NAMES.get(tgt, tgt)}, written in its own script. Do not leave "
                 "English words in English: use the word a native speaker would say. Only people's names, place "
                 "names and brand names stay as they are, and even those are written in the target script.")
    return f"""Translate each spoken line from {LANG_NAMES.get(src, src)} into {LANG_NAMES.get(tgt, tgt)} for a voice-over.
Spoken register, not written. {words} Write numbers as digits.
Return one item per input id, same ids, JSON only.

Lines:
{json.dumps(items, ensure_ascii=False)}"""


def shorten_prompt(items: list[dict], lang: str) -> str:
    return f"""These {LANG_NAMES.get(lang, lang)} voice-over lines are too long for the time they have in the video.
Rewrite each one shorter so it fits, keeping its full meaning and intent: drop filler and repetition, use
shorter words and phrasing, never drop the point of the line or add anything. Keep the same language and
script, spoken register. Stay within max_chars (counting spaces). "original" is the source line it translates.

Return one item per input id, same ids, JSON only.

Lines:
{json.dumps(items, ensure_ascii=False)}"""


KEY_REST_S = 60          # a key that hit its quota (429) anyway sits out this long; the others carry on
MAX_WAIT_S = 65          # longest a call waits for a key to free up before failing (the job retries later)


class _KeyQuota:
    """One Gemini key's own limits (GEMINI_KEY_RPM / TPM / RPD), counted over sliding windows.
    Kept in the worker process: one editor-worker makes every Gemini call. A restart forgets the day's
    count, so the day limit is a guard, not an exact mirror of Google's."""

    def __init__(self) -> None:
        self.calls_min: deque[float] = deque()
        self.calls_day: deque[float] = deque()
        self.tokens_min: deque[tuple[float, int]] = deque()
        self.rest_until = 0.0

    def wait_for(self, tokens: int, now: float) -> float | None:
        """Seconds until this key can take a call of `tokens`: 0 = now, None = not within MAX_WAIT_S."""
        for q, span in ((self.calls_min, 60), (self.calls_day, 86_400)):
            while q and now - q[0] >= span:
                q.popleft()
        while self.tokens_min and now - self.tokens_min[0][0] >= 60:
            self.tokens_min.popleft()
        if len(self.calls_day) >= GEMINI_KEY_RPD:
            return None
        waits = [max(0.0, self.rest_until - now)]
        if len(self.calls_min) >= GEMINI_KEY_RPM:
            waits.append(60 - (now - self.calls_min[0]))
        used = sum(n for _, n in self.tokens_min)
        if used + tokens > GEMINI_KEY_TPM and self.tokens_min:
            waits.append(60 - (now - self.tokens_min[0][0]))
        w = max(waits)
        return w if w <= MAX_WAIT_S else None

    def record(self, tokens: int, now: float) -> None:
        self.calls_min.append(now)
        self.calls_day.append(now)
        self.tokens_min.append((now, tokens))


def _tokens(prompt: str) -> int:
    # Indic scripts run close to one token per character; counting every character errs on the safe side.
    return len(prompt)


class GeminiLanguage:
    """Gemini over one or more API keys. Each call goes to the next key (round-robin) that is under its
    own per-minute, per-token and per-day quota; if every key is full it waits for the first free slot.
    A key that answers 429 anyway rests for KEY_REST_S and the same call moves to another key. When no
    key frees up within MAX_WAIT_S, the call fails (ProviderError) and the job is retried later."""

    def __init__(self, keys: list[str] | None = None) -> None:
        from google import genai
        keys = keys or GOOGLE_API_KEYS
        self.clients = [genai.Client(api_key=k) for k in keys]
        self.quota = [_KeyQuota() for _ in self.clients]
        self.next = 0
        self.lock = asyncio.Lock()

    async def _take_key(self, tokens: int, exclude: set[int]) -> int:
        """Reserve a slot on a key and return its index (waits if all are momentarily full)."""
        n = len(self.clients)
        async with self.lock:
            while True:
                now = time.monotonic()
                best, best_wait = None, None
                for k in range(n):
                    i = (self.next + k) % n
                    if i in exclude:
                        continue
                    w = self.quota[i].wait_for(tokens, now)
                    if w is not None and (best_wait is None or w < best_wait):
                        best, best_wait = i, w
                    if w == 0:
                        break
                if best is None:
                    raise ProviderError(f"Every Gemini key ({n}) is at its quota; retrying later.")
                if best_wait == 0:
                    self.quota[best].record(tokens, now)
                    self.next = (best + 1) % n
                    return best
                await asyncio.sleep(best_wait)

    async def _json(self, prompt: str, schema: dict) -> object:
        from google.genai import errors as gerrors
        from google.genai import types
        tokens, tried = _tokens(prompt), set()
        while True:
            i = await self._take_key(tokens, tried)
            try:
                r = await self.clients[i].aio.models.generate_content(
                    model=LLM_MODEL,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2, response_mime_type="application/json", response_json_schema=schema,
                    ),
                )
                break
            except gerrors.APIError as e:
                if e.code == 429:
                    self.quota[i].rest_until = time.monotonic() + KEY_REST_S
                    tried.add(i)
                    log.warning("Gemini key #%d hit its quota; resting it %ds", i + 1, KEY_REST_S)
                    if len(tried) < len(self.clients):
                        continue                                    # same call, another key
                    raise ProviderError(f"Gemini is over quota on every key ({e.code}): {e.message}") from e
                if (e.code or 500) >= 500:
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

    async def shorten(self, items: list[dict], lang: str) -> object:
        """items: [{id, text, original, audio_ms, available_ms, max_chars}] → [{id, text}]."""
        return await self._json(shorten_prompt(items, lang), TRANSLATE_SCHEMA)


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

    async def shorten(self, items: list[dict], lang: str) -> object:
        return [{"id": it["id"], "text": it["text"][: it["max_chars"]].rstrip()} for it in items]


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
