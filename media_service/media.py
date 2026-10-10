"""FFmpeg / FFprobe in isolated subprocesses — never in-process, never in the API."""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

from .config import FFMPEG_BIN_DIR, FFMPEG_TIMEOUT_SECONDS, PROXY_LONGEST_SIDE

log = logging.getLogger("media.ffmpeg")


class MediaError(RuntimeError):
    pass


def _binary(name: str) -> str:
    """Resolve ffmpeg/ffprobe: PATH first, then FFMPEG_BIN_DIR from .env.

    The worker inherits whatever PATH its launcher had; a terminal opened before
    ffmpeg was installed (or a background Start-Process) won't see it. Pinning
    FFMPEG_BIN_DIR makes that impossible to hit again.
    """
    found = shutil.which(name)
    if found:
        return found
    if FFMPEG_BIN_DIR:
        cand = Path(FFMPEG_BIN_DIR) / (f"{name}.exe" if os.name == "nt" else name)
        if cand.is_file():
            return str(cand)
    return name  # subprocess raises FileNotFoundError → clear MediaError below


def run(args: list[str], timeout: int = FFMPEG_TIMEOUT_SECONDS) -> str:
    """Run a media binary; raise MediaError with the stderr tail on failure."""
    argv = [_binary(args[0]), *args[1:]]
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        raise MediaError(
            f"{args[0]} isn't installed or isn't on PATH"
            + (f" (also checked {FFMPEG_BIN_DIR})." if FFMPEG_BIN_DIR else ".")
        )
    except subprocess.TimeoutExpired:
        raise MediaError(f"{args[0]} timed out after {timeout}s.")
    if p.returncode != 0:
        tail = (p.stderr or "").strip()[-800:]
        raise MediaError(f"{args[0]} failed (exit {p.returncode}): {tail}")
    return p.stdout


def probe(src: str) -> dict:
    """ffprobe metadata: duration (s), streams, fps, resolution, has_audio/video."""
    out = run([
        "ffprobe", "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", src,
    ])
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        raise MediaError("ffprobe returned unreadable output.")
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    duration = float(data.get("format", {}).get("duration") or v.get("duration") or 0)
    fps = None
    if v and v.get("avg_frame_rate") not in (None, "0/0"):
        num, _, den = str(v["avg_frame_rate"]).partition("/")
        try:
            fps = float(num) / float(den or 1)
        except (ValueError, ZeroDivisionError):
            fps = None
    return {
        "duration": duration,
        "has_video": v is not None,
        "has_audio": a is not None,
        "width": v.get("width") if v else None,
        "height": v.get("height") if v else None,
        "fps": fps,
        "video_codec": v.get("codec_name") if v else None,
        "audio_codec": a.get("codec_name") if a else None,
    }


def scale_filter(longest_side: int = PROXY_LONGEST_SIDE) -> str:
    """Cap the longest side, never upscale, keep aspect ratio, even dimensions (-2)."""
    s = int(longest_side)
    return (
        f"scale='if(gt(iw,ih),min(iw,{s}),-2)':'if(gt(iw,ih),-2,min(ih,{s}))'"
    )


def proxy_args(src: str, dst: str, longest_side: int = PROXY_LONGEST_SIDE) -> list[str]:
    """Re-encode for playback.

    Orientation: ffmpeg auto-applies rotation metadata on decode (no -noautorotate).
    Timestamps: original frame rate is kept (no fps filter); duration is verified
    after encoding. Longest side capped at `longest_side`.
    """
    return [
        "ffmpeg", "-y", "-i", src,
        "-vf", scale_filter(longest_side),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-map", "0:v:0", "-map", "0:a?",
        "-movflags", "+faststart",
        dst,
    ]


def thumbnail_args(src: str, dst: str, offset_s: float, width: int = 640) -> list[str]:
    """Poster JPG at ~10% in (or 1 s), height-capped 360p-ish."""
    return [
        "ffmpeg", "-y", "-ss", f"{max(0.0, offset_s):.3f}", "-i", src,
        "-frames:v", "1", "-vf", f"scale='min({width},iw)':-2",
        "-q:v", "3", dst,
    ]
