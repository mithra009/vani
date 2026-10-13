"""Where each chunk sits in source-video time (design §6.3b).

Speech input: a chunk's start/end come from interpolating its character offsets inside the
STT segment timing. A boundary inside a segment is an estimate the user can drag later.
Script input (C2-proposal): end to end from 0 with a fixed gap; chunks past the video end
are flagged `overflow`, never dropped.
"""

from __future__ import annotations

from dataclasses import dataclass

from .chunking import Chunk, Transcript


@dataclass(frozen=True)
class Anchor:
    start_s: float
    len_s: float
    overflow: bool = False


def time_at(spans: tuple[tuple[int, int, float, float], ...], char: int) -> float:
    """Segments are joined by one space, so an inclusive [a, b] lookup is never ambiguous:
    a chunk start is a segment character, an (exclusive) chunk end is a character or a joint."""
    if not spans:
        raise ValueError("No timed segments to place against.")
    for a, b, t0, t1 in spans:
        if a <= char <= b:
            return t0 + ((char - a) / (b - a) if b > a else 0.0) * (t1 - t0)
        if char < a:
            return t0
    return spans[-1][3]


def place_speech(transcript: Transcript, chunks: list[Chunk]) -> list[Anchor]:
    out = []
    for c in chunks:
        start = time_at(transcript.spans, c.char_start)
        end = time_at(transcript.spans, c.char_end)
        out.append(Anchor(round(start, 3), round(max(0.05, end - start), 3)))
    return out


def estimate_seconds(text: str, cps: float, speed: float = 1.0) -> float:
    return len(text) / (cps * speed)


def place_script(chunks: list[Chunk], video_s: float, cps: float, gap_s: float) -> list[Anchor]:
    out, t = [], 0.0
    for c in chunks:
        length = estimate_seconds(c.text, cps)
        out.append(Anchor(round(t, 3), round(length, 3), overflow=t + length > video_s))
        t += length + gap_s
    return out
