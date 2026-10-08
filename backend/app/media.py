"""Audio/video work: ffprobe/ffmpeg via subprocess, numpy for sample-exact assembly."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf

from .config import MIX_SR, STT_SR


class MediaError(RuntimeError):
    pass


def run(args: list[str]) -> str:
    p = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise MediaError(f"{Path(args[0]).name} failed: {p.stderr.strip()[-600:]}")
    return p.stdout


def ffmpeg(*args: str) -> None:
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", *args])


def probe(path: Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)])
    info = json.loads(out)
    streams = info.get("streams", [])
    return {
        "duration": float(info.get("format", {}).get("duration") or 0),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "has_video": any(s.get("codec_type") == "video" for s in streams),
    }


def extract_audio(src: Path, dst: Path, sr: int, mono: bool = True) -> Path:
    ffmpeg("-i", str(src), "-vn", "-ac", "1" if mono else "2", "-ar", str(sr), "-c:a", "pcm_s16le", str(dst))
    return dst


def to_upload_opus(src: Path, dst: Path) -> Path:
    """Small file for Batch STT's 10 MB direct-upload limit (~2.4 MB per 10 min)."""
    ffmpeg("-i", str(src), "-vn", "-ac", "1", "-ar", str(STT_SR), "-c:a", "libopus", "-b:a", "32k", str(dst))
    return dst


def read(path: Path, sr: int | None = None) -> tuple[np.ndarray, int]:
    data, file_sr = sf.read(str(path), dtype="float32", always_2d=False)
    if data.ndim > 1:
        data = data.mean(axis=1)
    if sr and file_sr != sr:
        tmp = path.with_suffix(f".{sr}.wav")
        ffmpeg("-i", str(path), "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", str(tmp))
        data, file_sr = sf.read(str(tmp), dtype="float32", always_2d=False)
    return data, file_sr


def write(path: Path, data: np.ndarray, sr: int) -> Path:
    sf.write(str(path), np.clip(data, -1, 1), sr, subtype="PCM_16")
    return path


def cut(src: Path, dst: Path, start: float, end: float, sr: int = STT_SR) -> Path:
    ffmpeg("-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", str(src), "-ac", "1", "-ar", str(sr), "-c:a", "pcm_s16le", str(dst))
    return dst


def trim_silence(x: np.ndarray, sr: int, thresh_db: float = -45.0, pad_s: float = 0.02) -> np.ndarray:
    """Drop leading/trailing silence that TTS engines add (PLAN §5.5 step 3)."""
    if not len(x):
        return x
    win = max(1, int(sr * 0.01))
    n = len(x) // win
    if n == 0:
        return x
    frames = x[: n * win].reshape(n, win)
    db = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    loud = np.where(db > thresh_db)[0]
    if not len(loud):
        return x[:0]
    pad = int(pad_s * sr)
    a = max(0, loud[0] * win - pad)
    b = min(len(x), (loud[-1] + 1) * win + pad)
    return x[a:b]


def atempo(x: np.ndarray, sr: int, factor: float, workdir: Path) -> np.ndarray:
    """Pitch-preserving speed change via ffmpeg atempo (0.5–2.0 per filter instance)."""
    if abs(factor - 1.0) < 0.005:
        return x
    src = write(workdir / "_atempo_in.wav", x, sr)
    dst = workdir / "_atempo_out.wav"
    ffmpeg("-i", str(src), "-filter:a", f"atempo={factor:.4f}", "-ar", str(sr), str(dst))
    y, _ = read(dst)
    return y


def fade(x: np.ndarray, sr: int, ms: float = 10) -> np.ndarray:
    n = min(len(x) // 2, int(sr * ms / 1000))
    if n <= 0:
        return x
    y = x.copy()
    ramp = np.linspace(0, 1, n, dtype=np.float32)
    y[:n] *= ramp
    y[-n:] *= ramp[::-1]
    return y


def place(timeline: np.ndarray, clip: np.ndarray, start_s: float, sr: int) -> None:
    """Absolute placement by sample index, so errors never accumulate (PLAN §5.6)."""
    i = int(round(start_s * sr))
    if i >= len(timeline):
        return
    end = min(len(timeline), i + len(clip))
    timeline[i:end] += clip[: end - i]


def loudnorm(src: Path, dst: Path, target_lufs: float = -16.0) -> Path:
    ffmpeg("-i", str(src), "-af", f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11", "-ar", str(MIX_SR), "-ac", "1", str(dst))
    return dst


def clean_voice(src: Path, dst: Path) -> Path:
    """Narration clean-up: rumble high-pass, FFT denoise, gentle compression, loudness."""
    ffmpeg("-i", str(src), "-af",
           "highpass=f=80,afftdn=nf=-25,acompressor=threshold=-20dB:ratio=3:attack=5:release=80,loudnorm=I=-16:TP=-1.5",
           "-ar", str(MIX_SR), "-ac", "1", str(dst))
    return dst


def mix_and_mux(video: Path, voice_track: Path, out: Path, bg_mode: str, duration: float, label_ai: bool) -> Path:
    """Duck: original audio compressed by the voice (sidechain); mute: voice only.
    Video stream copied untouched; audio trimmed/padded to the exact video duration."""
    meta = ["-metadata", "comment=Contains an AI-generated voice"] if label_ai else []
    has_audio = probe(video)["has_audio"]
    if bg_mode == "duck" and has_audio:
        fc = ("[0:a]aresample=48000,aformat=channel_layouts=stereo[bg];"
              "[1:a]aformat=channel_layouts=stereo,asplit=2[v1][v2];"
              "[bg][v1]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=300:makeup=1[ducked];"
              "[ducked][v2]amix=inputs=2:duration=first:normalize=0,"
              f"apad,atrim=0:{duration:.6f}[a]")
    else:
        fc = f"[1:a]aformat=channel_layouts=stereo,apad,atrim=0:{duration:.6f}[a]"
    ffmpeg("-i", str(video), "-i", str(voice_track), "-filter_complex", fc,
           "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
           "-ar", "48000", *meta, "-movflags", "+faststart", str(out))
    return out


def srt(segments: list[dict], key: str) -> str:
    import re

    def t(s: float) -> str:
        ms = int(round(s * 1000))
        return f"{ms // 3600000:02d}:{ms % 3600000 // 60000:02d}:{ms % 60000 // 1000:02d},{ms % 1000:03d}"

    out = []
    for i, s in enumerate(segments, 1):
        text = re.sub(r"<[^>]+>\s*", "", s.get(key) or "").strip()
        if text:
            out.append(f"{i}\n{t(s['start_s'])} --> {t(s['end_s'])}\n{text}\n")
    return "\n".join(out)
