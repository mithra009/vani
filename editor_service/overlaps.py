"""Fixing overlapping voice lines, on the user's request (no automatic changes).

A line overlaps when its audio is still playing as the next line starts. The next line's start is pinned
to its place in the video, so only the line that runs over changes. Two fixes:

  speed    exact: Vani changes speed with ffmpeg atempo on a 1.0 take, so a speed of s makes the audio
           raw × (current speed / s) long. Pick the smallest s (to 0.01) that ends GAP_S before the next
           line; past MAX_SPEED the line can't be fixed this way and is reported.
  shorten  Gemini rewrites the line within a character budget scaled to the time available
           (providers.shorten_prompt); the chunk is then re-voiced at its current speed.
"""

from __future__ import annotations

import math

from . import timeline

GAP_S = 0.05            # breathing room left before the next line starts
MAX_SPEED = 2.0
SHORTEN_MARGIN = 0.92   # aim a little under the budget: speech length doesn't scale exactly with characters


def overlapping(doc: dict, chunks: list[dict]) -> list[dict]:
    """Lines whose audio runs into the next line's start, with their timings (seconds).
    → [{chunk_id, text, source_text, speed, raw_s, trims_s, length_s, available_s}]"""
    placed, _ = timeline.layout(doc, [dict(c, id=str(c["id"])) for c in chunks if c["status"] == "ready"])
    audible = sorted((p for p in placed if not p.muted and p.length > 0), key=lambda p: p.t)
    by_id = {str(c["id"]): c for c in chunks}
    out = []
    for i, a in enumerate(audible):
        nxt = next((b.t for b in audible[i + 1:] if b.t > a.t + timeline.EPS), None)
        if nxt is None or a.t + a.length <= nxt + timeline.EPS:
            continue
        c = by_id[a.chunk_id]
        raw = float(c["audio_duration_s"])
        out.append({
            "chunk_id": a.chunk_id, "text": c["text"], "source_text": c["source_text"], "speed": float(c["speed"]),
            "raw_s": raw, "trims_s": round(raw - a.length, 6), "length_s": a.length,
            "available_s": round(max(0.0, nxt - a.t - GAP_S), 6),
        })
    return out


def speed_to_fit(line: dict) -> float | None:
    """Smallest speed (to 0.01) that ends the line in time, or None when even MAX_SPEED is too slow.
    Trims are seconds of the audio and stay as they are; only the spoken part gets faster."""
    room = line["available_s"] + line["trims_s"]
    if room <= 0:
        return None
    s = math.ceil(line["raw_s"] * line["speed"] / room * 100 - 1e-9) / 100
    s = max(s, line["speed"])
    return s if s <= MAX_SPEED + 1e-9 else None


def shorten_budget(line: dict) -> int:
    """Characters the line can keep so its audio, at the same speed, fits the time available."""
    ratio = line["available_s"] / line["length_s"] if line["length_s"] > 0 else 0
    return max(1, int(len(line["text"]) * ratio * SHORTEN_MARGIN))
