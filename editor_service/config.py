"""Settings for the editor service, read once from the repo-root .env."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from media_service.limits import limit

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# Same Postgres + bucket as the media service (direct connection or session pooler).
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
EDITOR_API_PORT = int(os.getenv("EDITOR_API_PORT", "8030"))
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]

# FAKE_PROVIDERS=1 (the default here) swaps Gnani and Gemini for local stand-ins: no credits.
# Set FAKE_PROVIDERS=0 only for a deliberate pilot.
FAKE_PROVIDERS = os.getenv("FAKE_PROVIDERS", "1") == "1"
GNANI_API_KEY = os.getenv("GNANI_API_KEY", "").strip()
GOOGLE_API_KEY = (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY") or "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite")

MAX_VIDEO_SECONDS = limit("uploads", "max_video_seconds", 600, "MAX_VIDEO_SECONDS")          # C10
MAX_SCRIPT_CHARS = 20_000
MAX_NARRATION_BYTES = limit("uploads", "max_narration_mb", 100_000_000, "MAX_NARRATION_BYTES", scale=1_000_000)

# Chunking (C1-proposal): about one sentence, 3–8 s of speech.
CHUNK_TARGET_MIN_S, CHUNK_TARGET_MAX_S = 3.0, 8.0
CHUNK_LLM_ATTEMPTS = 2                 # one retry on invalid Gemini output, then fail loudly

# Script placement (C2-proposal): end to end from 0 with a gap; flag overflow past the video.
SCRIPT_GAP_S = 0.3
DEFAULT_CPS = 13.0                     # chars/s used only to estimate script chunk length

TTS_SPEED_MIN, TTS_SPEED_MAX = 0.5, 2.0       # what a chunk may ask for
GNANI_SPEED_MIN, GNANI_SPEED_MAX = 0.85, 1.15  # Timbre's own range; the rest is ffmpeg atempo (pitch kept)
TTS_SR = 48_000
STT_SR = 16_000

# Every limit below is set in config/limits.toml (env vars override); see that file for meanings.
# Shared provider budgets: calls per minute for the WHOLE app, split fairly (ratelimit.py).
RATE_LIMITS = {
    "gnani_tts": limit("providers", "gnani_tts_per_min", 60, "GNANI_TTS_RPM"),
    "gnani_stt": limit("providers", "gnani_stt_per_min", 4, "GNANI_STT_RPM"),
    "gemini": limit("providers", "gemini_per_min", 30, "GEMINI_RPM"),
}
MAX_PROJECTS_PER_USER = limit("projects", "max_per_user", 50, "MAX_PROJECTS_PER_USER")
MAX_ACTIVE_GENERATIONS = limit("projects", "max_generating_per_user", 3, "MAX_ACTIVE_GENERATIONS")
BUSY_ACTIVE_USERS = limit("projects", "busy_active_users", 10, "BUSY_ACTIVE_USERS")
MAX_QUEUED_EXPORTS_PER_USER = limit("projects", "max_queued_exports_per_user", 2, "MAX_QUEUED_EXPORTS_PER_USER")

# Worker queue behaviour (mirrors media_service/config.py).
JOB_MAX_ATTEMPTS = int(os.getenv("EDITOR_JOB_MAX_ATTEMPTS", "4"))
JOB_RETRY_BASE_SECONDS = int(os.getenv("EDITOR_JOB_RETRY_BASE_SECONDS", "15"))
WORKER_POLL_SECONDS = float(os.getenv("WORKER_POLL_SECONDS", "0.5"))
WORKER_STALE_JOB_SECONDS = int(os.getenv("EDITOR_WORKER_STALE_JOB_SECONDS", "2400"))
WORKER_REAP_SECONDS = float(os.getenv("WORKER_REAP_SECONDS", "60"))
EVENTS_POLL_SECONDS = 1.0
EXPORT_TIMEOUT_SECONDS = int(os.getenv("EXPORT_TIMEOUT_SECONDS", "1800"))


def check_providers() -> None:
    """Fail at startup, not mid-job, when real providers are selected without keys."""
    if FAKE_PROVIDERS:
        return
    missing = [n for n, v in (("GNANI_API_KEY", GNANI_API_KEY), ("GOOGLE_API_KEY", GOOGLE_API_KEY)) if not v]
    if missing:
        raise RuntimeError(f"FAKE_PROVIDERS=0 but {', '.join(missing)} missing from .env.")
