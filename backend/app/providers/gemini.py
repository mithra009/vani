"""Gemini 3.5 Flash-Lite for length-budgeted translation and emotion labelling
(PLAN.md §4.3, §5.4, §5.9.2). Structured JSON output so parsing never guesses."""

from __future__ import annotations

import json

from google import genai
from google.genai import types

from ..config import GOOGLE_API_KEY, LLM_MODEL
from ..emotion import EMOTIONS

LANG_NAMES = {
    "hi-IN": "Hindi (Devanagari script)", "en-IN": "Indian English", "ta-IN": "Tamil (Tamil script)",
    "te-IN": "Telugu (Telugu script)", "kn-IN": "Kannada (Kannada script)", "ml-IN": "Malayalam (Malayalam script)",
    "mr-IN": "Marathi (Devanagari script)", "bn-IN": "Bengali (Bengali script)", "gu-IN": "Gujarati (Gujarati script)",
    "pa-IN": "Punjabi (Gurmukhi script)", "hi-en": "Hinglish (Hindi with natural English words, written in Roman script)",
}

ALLOWED_TAGS = ["laugh", "chuckle", "giggle", "sigh", "exhales", "sniffles", "whispers", "softly",
                "shouting", "high-pitched", "stammers", "rushed", "slow", "pauses"]


class GeminiLLM:
    def __init__(self) -> None:
        if not GOOGLE_API_KEY:
            raise RuntimeError("GOOGLE_API_KEY is missing from .env.")
        self.client = genai.Client(api_key=GOOGLE_API_KEY)

    async def _json(self, prompt: str, schema: dict) -> object:
        r = await self.client.aio.models.generate_content(
            model=LLM_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.3,
                response_mime_type="application/json",
                response_json_schema=schema,
            ),
        )
        return json.loads(r.text)

    async def translate(self, items: list[dict], src: str, tgt: str) -> list[dict]:
        """items: {id, text, context_before, context_after, emotion, intensity, nonverbal, budget, tags}
        → [{id, natural, short}]"""
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"id": {"type": "integer"}, "natural": {"type": "string"}, "short": {"type": "string"}},
                "required": ["id", "natural", "short"],
            },
        }
        prompt = f"""You translate video dialogue for dubbing from {LANG_NAMES.get(src, src)} into {LANG_NAMES.get(tgt, tgt)}.
Each line will be spoken aloud by a text-to-speech voice inside a fixed time slot.

For every line return:
- "natural": a faithful, natural spoken translation. Aim for at most `budget` characters (tags excluded).
- "short": the same meaning in at most 80% of `budget` characters, still natural.

Rules:
- Spoken register, not written. Keep names, numbers, brands and technical words as they are.
- Write numbers as digits.
- Emotion tags: if a line has `tags`, put each tag exactly once in angle brackets at the point it
  belongs, e.g. "<laugh>" right after the funny part, "<whispers>" at the start of a whispered line.
  Use ONLY tags listed in that line's `tags`. Never invent other tags. Lines with no tags get none.
- Do not add explanations. Return JSON only.

Lines:
{json.dumps(items, ensure_ascii=False)}"""
        out = await self._json(prompt, schema)
        return out if isinstance(out, list) else []

    async def label_emotions(self, lines: list[dict], lang: str) -> list[dict]:
        """lines: {id, text} → [{id, emotion, intensity, nonverbal}]"""
        schema = {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "emotion": {"type": "string", "enum": list(EMOTIONS)},
                    "intensity": {"type": "integer", "minimum": 1, "maximum": 3},
                    "nonverbal": {"type": "array", "items": {"type": "string", "enum": ["laugh", "chuckle", "giggle", "sigh", "exhales", "sniffles"]}},
                },
                "required": ["id", "emotion", "intensity", "nonverbal"],
            },
        }
        prompt = f"""Label the emotion of each spoken line from a video transcript ({LANG_NAMES.get(lang, lang)}).
Use the lines around each one as context. Choose one of: {", ".join(EMOTIONS)}.
"fearful" covers nervous or scared. "tender" covers warm and gentle. Use "whisper" only if the words
suggest whispering or a secret. Most lines are "neutral"; don't over-label.
intensity: 1 mild, 2 clear, 3 strong.
nonverbal: sounds the text implies happened (e.g. "haha" → laugh, an exasperated "uff" → sigh); usually empty.

Lines:
{json.dumps(lines, ensure_ascii=False)}"""
        out = await self._json(prompt, schema)
        return out if isinstance(out, list) else []
