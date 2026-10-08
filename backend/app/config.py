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
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3.5-flash-lite")

# FAKE_PROVIDERS=1 swaps Gnani and Gemini for local stand-ins (no network, no credits).
FAKE_PROVIDERS = os.getenv("FAKE_PROVIDERS", "0") == "1"

MAX_VIDEO_SECONDS = 600
MAX_UPLOAD_BYTES = 500_000_000
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
