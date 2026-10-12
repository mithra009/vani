"""Gemini cuts the transcript into chunks and tags each with a Gnani emotion (D4, D7).

Gemini may only *cut* the text, never rewrite it. `locate` proves that: every chunk must be
the next contiguous span of the transcript (whitespace between chunks is the only slack), and
the chunks must cover all of it. Anything else raises OutputInvalid — no silent repair.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import OutputInvalid

# Gnani Timbre v2.5 inline audio tags (same list the dubbing backend sends Gemini).
EMOTION_TAGS = ("laugh", "chuckle", "giggle", "sigh", "exhales", "sniffles", "whispers", "softly",
                "shouting", "high-pitched", "stammers", "rushed", "slow", "pauses")
NEUTRAL = "neutral"
ALLOWED = frozenset(EMOTION_TAGS) | {NEUTRAL}


@dataclass(frozen=True)
class Transcript:
    text: str
    # (char_start, char_end, start_s, end_s) per STT segment, in order.
    spans: tuple[tuple[int, int, float, float], ...]


@dataclass(frozen=True)
class Chunk:
    idx: int
    char_start: int
    char_end: int
    text: str
    emotion_tag: str


def build_transcript(segments: list[dict]) -> Transcript:
    """Join STT segments with single spaces and remember where each one sits."""
    parts, spans, pos = [], [], 0
    for s in segments:
        t = " ".join(str(s.get("text", "")).split())
        if not t:
            continue
        if parts:
            pos += 1
        spans.append((pos, pos + len(t), float(s["start_s"]), float(s["end_s"])))
        parts.append(t)
        pos += len(t)
    return Transcript(" ".join(parts), tuple(spans))


def script_transcript(script: str) -> Transcript:
    text = " ".join(script.split())
    return Transcript(text, ())


def locate(transcript: str, pieces: list[str]) -> list[tuple[int, int]]:
    out, pos, n = [], 0, len(transcript)
    for i, raw in enumerate(pieces):
        piece = " ".join(str(raw).split())
        if not piece:
            raise OutputInvalid(f"Chunk {i} is empty.", "chunking_invalid")
        while pos < n and transcript[pos].isspace():
            pos += 1
        if transcript[pos:pos + len(piece)] != piece:
            got = piece[:40]
            want = transcript[pos:pos + 40]
            raise OutputInvalid(
                f"Chunk {i} doesn't continue the transcript (got {got!r}, expected {want!r}).",
                "chunking_invalid",
            )
        out.append((pos, pos + len(piece)))
        pos += len(piece)
    if transcript[pos:].strip():
        raise OutputInvalid(
            f"Chunks stop early; {len(transcript[pos:].strip())} characters were dropped.",
            "chunking_invalid",
        )
    return out


def validate(transcript: Transcript, raw: object) -> list[Chunk]:
    """raw: the model's parsed JSON, expected [{text, emotion_tag}, ...]."""
    if not isinstance(raw, list) or not raw:
        raise OutputInvalid("Chunking returned no chunks.", "chunking_invalid")
    texts, tags = [], []
    for i, item in enumerate(raw):
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise OutputInvalid(f"Chunk {i} is malformed: {item!r}"[:200], "chunking_invalid")
        tag = item.get("emotion_tag", NEUTRAL)
        if tag not in ALLOWED:
            raise OutputInvalid(f"Chunk {i} has unsupported emotion tag {tag!r}.", "chunking_invalid")
        texts.append(item["text"])
        tags.append(tag)
    spans = locate(transcript.text, texts)
    return [Chunk(i, a, b, transcript.text[a:b], tags[i]) for i, (a, b) in enumerate(spans)]


def tts_text(text: str, emotion_tag: str) -> str:
    return text if emotion_tag == NEUTRAL else f"<{emotion_tag}> {text}"
