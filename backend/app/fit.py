"""Timing logic (PLAN.md §5.2, §5.4, §5.5). Pure functions: no I/O, fully unit-tested."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import (ATEMPO_MAX, FLAG_STRETCH_MAX, GAP_BORROW_S, SLOT_GUARD_S,
                     TOTAL_PACE_CAP, TTS_SPEED_MAX, TTS_SPEED_MIN)

# Starting estimates of characters per second at speed 1.0. Replaced per voice by the
# running mean of real TTS output (store.record_voice_cps).
DEFAULT_CPS = {
    "hi-IN": 13.0, "en-IN": 14.0, "hi-en": 14.0, "ta-IN": 12.0, "te-IN": 12.0, "kn-IN": 12.0,
    "ml-IN": 11.0, "mr-IN": 12.5, "bn-IN": 12.5, "gu-IN": 12.5, "pa-IN": 13.0,
}

# Time a tag adds to speech (PLAN §5.9.3); silence tags are documented, the rest estimated.
TAG_SECONDS = {
    "pauses": 0.75, "long_pause": 2.0, "laugh": 0.6, "laughs harder": 0.9, "chuckle": 0.4,
    "giggle": 0.5, "sigh": 0.5, "exhales": 0.4, "sniffles": 0.3, "coughs": 0.4,
    "clears throat": 0.5, "yawns": 0.8,
}
TAG_RE = re.compile(r"<([^>]+)>")

MERGE_SHORTER_S = 1.2
MERGE_GAP_S = 0.3
SPLIT_LONGER_S = 12.0


def normalise(segments: list[dict], pauses: list[tuple[float, float]] | None = None) -> list[dict]:
    """Merge very short segments into a close neighbour; split very long ones at the widest
    internal pause (pauses = list of (start, end) silences found in the audio)."""
    segs = [dict(s) for s in sorted(segments, key=lambda s: s["start_s"]) if (s.get("text") or "").strip()]
    merged: list[dict] = []
    for s in segs:
        prev = merged[-1] if merged else None
        short = (s["end_s"] - s["start_s"]) < MERGE_SHORTER_S or (prev and (prev["end_s"] - prev["start_s"]) < MERGE_SHORTER_S)
        if prev and short and s["start_s"] - prev["end_s"] < MERGE_GAP_S and s.get("speaker") == prev.get("speaker"):
            prev["end_s"] = s["end_s"]
            prev["text"] = f"{prev['text'].rstrip()} {s['text'].lstrip()}"
        else:
            merged.append(s)

    out: list[dict] = []
    for s in merged:
        out.extend(_split(s, pauses or []))
    return out


def _split(s: dict, pauses: list[tuple[float, float]]) -> list[dict]:
    if s["end_s"] - s["start_s"] <= SPLIT_LONGER_S:
        return [s]
    inside = [(a, b) for a, b in pauses if a > s["start_s"] + 2 and b < s["end_s"] - 2]
    if not inside:
        return [s]
    a, b = max(inside, key=lambda p: p[1] - p[0])
    cut = (a + b) / 2
    frac = (cut - s["start_s"]) / (s["end_s"] - s["start_s"])
    words = s["text"].split()
    k = max(1, min(len(words) - 1, round(len(words) * frac)))
    left = {**s, "end_s": a, "text": " ".join(words[:k])}
    right = {**s, "start_s": b, "text": " ".join(words[k:])}
    return _split(left, pauses) + _split(right, pauses)


def slots(segments: list[dict], duration: float) -> list[dict]:
    """Each line may speak from its start until just before the next line starts."""
    out = []
    for i, s in enumerate(segments):
        last = i + 1 == len(segments)
        nxt = duration if last else segments[i + 1]["start_s"]
        slot_end = max(s["end_s"], nxt if last else nxt - SLOT_GUARD_S)
        out.append({**s, "slot_end_s": round(min(slot_end, duration), 3)})
    return out


def tag_seconds(text: str) -> float:
    return sum(TAG_SECONDS.get(t.strip(), 0.0) for t in TAG_RE.findall(text or ""))


def spoken_chars(text: str) -> int:
    return len(re.sub(r"\s+", " ", TAG_RE.sub("", text or "")).strip())


def predict_seconds(text: str, cps: float, speed: float = 1.0) -> float:
    return spoken_chars(text) / (cps * speed) + tag_seconds(text)


def char_budget(slot_s: float, cps: float) -> int:
    return max(4, int(slot_s * cps * 0.95))


def choose_speed(predicted_at_1: float, slot_s: float, emotion_speed: float = 1.0) -> float:
    """Speed so the predicted line fits its slot; the emotion's preferred pace is a nudge
    that fitting overrides (PLAN §5.5: fitting wins)."""
    need = predicted_at_1 / slot_s if slot_s > 0 else TTS_SPEED_MAX
    return round(min(TTS_SPEED_MAX, max(TTS_SPEED_MIN, need, emotion_speed)), 3)


@dataclass
class FitDecision:
    action: str          # place | stretch | retry_short | borrow | flag
    stretch: float = 1.0
    borrow_s: float = 0.0


def decide(actual_s: float, slot_s: float, next_gap_s: float, speed: float, tried_short: bool) -> FitDecision:
    """PLAN §5.5 step 4."""
    if actual_s <= slot_s:
        return FitDecision("place")
    ratio = actual_s / slot_s
    cap = TOTAL_PACE_CAP / max(speed, 1.0)
    if ratio <= min(ATEMPO_MAX, cap):
        return FitDecision("stretch", round(ratio, 4))
    if not tried_short:
        return FitDecision("retry_short")
    borrow = min(GAP_BORROW_S, max(0.0, next_gap_s))
    if actual_s <= slot_s + borrow:
        return FitDecision("borrow", 1.0, round(actual_s - slot_s, 3))
    ratio_b = actual_s / (slot_s + borrow)
    if ratio_b <= min(ATEMPO_MAX, cap):
        return FitDecision("borrow", round(ratio_b, 4), borrow)
    return FitDecision("flag", round(min(ratio_b, FLAG_STRETCH_MAX, cap), 4), borrow)
