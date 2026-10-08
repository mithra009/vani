"""Emotion transfer (PLAN.md §5.9): acoustic features from plain signal processing,
fused with the LLM's text label, smoothed, then mapped to Timbre controls."""

from __future__ import annotations

import numpy as np

EMOTIONS = ("neutral", "happy", "excited", "angry", "sad", "fearful", "whisper", "tender")

# Emotion → (tags by intensity ≥ 2, preferred speed). Intensity 1 = speed/punctuation only.
CONTROLS = {
    "neutral": ([], 1.00),
    "happy":   ([], 1.03),
    "excited": (["rushed"], 1.10),
    "angry":   (["shouting"], 1.08),
    "sad":     (["softly"], 0.90),
    "fearful": (["stammers"], 1.05),
    "whisper": (["whispers"], 0.95),
    "tender":  (["softly"], 0.92),
}
HIGH_AROUSAL = {"excited", "angry", "fearful"}
LOW_AROUSAL = {"sad", "tender", "whisper"}


def features(x: np.ndarray, sr: int) -> dict:
    """Loudness, pitch (autocorrelation on voiced frames), pitch spread, syllable rate,
    and spectral flatness as a breathiness proxy."""
    if len(x) < sr * 0.2:
        return {"rms_db": -80.0, "f0": 0.0, "f0_sd": 0.0, "rate": 0.0, "flatness": 0.0}
    win, hop = int(sr * 0.04), int(sr * 0.01)
    n = 1 + (len(x) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    frames = x[idx] * np.hanning(win)[None, :]
    rms = np.sqrt((frames ** 2).mean(axis=1) + 1e-12)
    rms_db = 20 * np.log10(rms)
    voiced = rms_db > (np.percentile(rms_db, 90) - 25)

    f0s = []
    lo, hi = int(sr / 400), int(sr / 70)
    for f in frames[voiced][:: max(1, voiced.sum() // 120)]:
        ac = np.correlate(f, f, mode="full")[win - 1:]
        if ac[0] <= 0:
            continue
        seg = ac[lo:hi]
        k = int(np.argmax(seg)) + lo
        if ac[k] / ac[0] > 0.35:
            f0s.append(sr / k)

    env = np.convolve(rms, np.ones(5) / 5, mode="same")
    peaks = (env[1:-1] > env[:-2]) & (env[1:-1] > env[2:]) & (20 * np.log10(env[1:-1] + 1e-12) > np.percentile(rms_db, 60))
    rate = peaks.sum() / (len(x) / sr)

    spec = np.abs(np.fft.rfft(frames[voiced] if voiced.any() else frames, axis=1)) + 1e-9
    flat = float(np.mean(np.exp(np.mean(np.log(spec), axis=1)) / np.mean(spec, axis=1)))

    return {
        "rms_db": float(np.mean(rms_db[voiced])) if voiced.any() else float(np.mean(rms_db)),
        "f0": float(np.median(f0s)) if f0s else 0.0,
        "f0_sd": float(np.std(f0s)) if len(f0s) > 2 else 0.0,
        "rate": float(rate),
        "flatness": flat,
    }


def baseline(all_feats: list[dict]) -> dict:
    keys = ("rms_db", "f0", "f0_sd", "rate", "flatness")
    out = {}
    for k in keys:
        v = np.array([f[k] for f in all_feats if f[k] > 0 or k == "rms_db"], dtype=float)
        out[k] = (float(v.mean()), float(v.std() + 1e-6)) if len(v) else (0.0, 1.0)
    return out


def arousal(feat: dict, base: dict) -> str:
    """'high' | 'low' | 'whisper' | 'normal' relative to the speaker's own baseline."""
    z = {k: (feat[k] - base[k][0]) / base[k][1] for k in base}
    if z["rms_db"] < -1.3 and z["flatness"] > 1.0:
        return "whisper"
    score = 0.6 * z["rms_db"] + 0.4 * z["f0"] + 0.3 * z["f0_sd"] + 0.3 * z["rate"]
    if score > 1.0:
        return "high"
    if score < -1.0:
        return "low"
    return "normal"


def fuse(text_label: str, intensity: int, arous: str) -> tuple[str, int]:
    """Text decides the type, acoustics the arousal. When they disagree, step down
    to the milder reading (PLAN §5.9.2)."""
    label = text_label if text_label in EMOTIONS else "neutral"
    if arous == "whisper":
        return "whisper", max(2, intensity)
    if label in HIGH_AROUSAL and arous == "low":
        return "neutral", 1
    if label in LOW_AROUSAL - {"whisper"} and arous == "high":
        return "neutral", 1
    if label == "neutral" and arous == "high":
        return "excited", 1
    if label in HIGH_AROUSAL and arous == "high":
        intensity = min(3, intensity + 1)
    return label, max(1, min(3, intensity))


def smooth(labels: list[tuple[str, int]]) -> list[tuple[str, int]]:
    """A label must hold for two lines unless it's strong (intensity 3)."""
    out = list(labels)
    for i, (lab, inten) in enumerate(labels):
        if lab == "neutral" or inten >= 3:
            continue
        prev_same = i > 0 and labels[i - 1][0] == lab
        next_same = i + 1 < len(labels) and labels[i + 1][0] == lab
        if not (prev_same or next_same):
            out[i] = (lab, 1)   # keep the type, drop it to speed/punctuation only
    return out


def controls(emotion: str, intensity: int) -> tuple[list[str], float]:
    tags, speed = CONTROLS.get(emotion, CONTROLS["neutral"])
    if intensity < 2:
        return [], 1.0 + (speed - 1.0) * 0.5
    if emotion == "excited" and intensity < 3:
        return [], speed
    return tags, speed
