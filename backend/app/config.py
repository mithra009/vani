"""Settings, read once from the environment (.env at the repo root)."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

STORAGE = Path(os.getenv("VANI_STORAGE", ROOT / "storage"))
DB_PATH = STORAGE / "vani.db"

GNANI_API_KEY = os.getenv("GNANI_API_KEY", "").strip()
GNANI_BASE = os.getenv("GNANI_BASE_URL", "https://api.vachana.ai")
# GEMINI_API_KEYS is the comma list the editor service rotates through; this service uses its first key.
GOOGLE_API_KEY = (os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
                  or os.getenv("GEMINI_API_KEYS") or "").split(",")[0].strip()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "").strip()
SUPABASE_JWKS_URL = os.getenv("SUPABASE_JWKS_URL", f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json").strip()

# Where project documents live: "supabase" (default when configured) or "sqlite" (tests, offline).
DB_BACKEND = os.getenv("VANI_DB", "supabase" if SUPABASE_URL and SUPABASE_SECRET_KEY else "sqlite")
# Tests only: skip token checks and act as one fixed local user.
AUTH_DISABLED = os.getenv("VANI_AUTH_DISABLED", "0") == "1"
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite")

# FAKE_PROVIDERS=1 swaps Gnani and Gemini for local stand-ins (no network, no credits).
FAKE_PROVIDERS = os.getenv("FAKE_PROVIDERS", "0") == "1"

MAX_VIDEO_SECONDS = 600
MAX_UPLOAD_BYTES = 500_000_000
# Projects one user may have transcribing or dubbing at once: the worker is shared, one job at a time.
MAX_ACTIVE_JOBS_PER_USER = int(os.getenv("MAX_ACTIVE_JOBS_PER_USER", "2"))
# Saved uploads keep one of these extensions, never the client's own, so a name like .m3u8
# can't make ffmpeg read the upload as a playlist of other files.
VIDEO_EXTS = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}
AUDIO_EXTS = {".webm", ".wav", ".mp3", ".m4a", ".ogg", ".opus", ".aac", ".flac", ".mp4"}
MIX_SR = 48_000          # timeline / mixing sample rate
STT_SR = 16_000

# Fit engine limits (PLAN.md §5.5)
TTS_SPEED_MIN, TTS_SPEED_MAX = 0.85, 1.15
ATEMPO_MAX = 1.15            # pitch-preserving stretch on top of TTS speed
FLAG_STRETCH_MAX = 1.25      # beyond this a line is flagged
TOTAL_PACE_CAP = 1.30        # speed × stretch never exceeds this
GAP_BORROW_S = 0.30
SLOT_GUARD_S = 0.12          # silence kept before the next line
TTS_CONCURRENCY = 3

STORAGE.mkdir(parents=True, exist_ok=True)
