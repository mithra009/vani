"""Settings for the media service, read once from the repo-root .env."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

from .limits import limit

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# Postgres — must be the direct connection (5432) or the session pooler.
# The transaction pooler (6543) breaks SELECT ... FOR UPDATE SKIP LOCKED.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY", "").strip()
SUPABASE_JWKS_URL = os.getenv(
    "SUPABASE_JWKS_URL", f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
).strip()

MEDIA_BUCKET = os.getenv("SUPABASE_MEDIA_BUCKET", "media").strip() or "media"

# Object storage for every file (videos, thumbnails, proxies, voice audio, exports).
# "s3" when S3_BUCKET is set, otherwise the Supabase bucket. Tables stay in Supabase either way.
# AWS credentials come from the standard AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY variables.
S3_BUCKET = os.getenv("S3_BUCKET", "").strip()
AWS_REGION = (os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "").strip()
# Optional: an S3-compatible endpoint (local test server, MinIO). Unset for AWS.
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "").strip()
STORAGE_BACKEND = (os.getenv("STORAGE_BACKEND") or ("s3" if S3_BUCKET else "supabase")).strip().lower()
MEDIA_API_PORT = int(os.getenv("MEDIA_API_PORT", "8020"))
ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
    if o.strip()
]

# Tests only: skip token checks and act as one fixed local user.
AUTH_DISABLED = os.getenv("VANI_AUTH_DISABLED", "0") == "1"

# Limits enforced before an upload URL is issued (mirrors backend/app/config.py).
# Values live in config/limits.toml ([uploads]); env vars still override.
MAX_VIDEO_SECONDS = limit("uploads", "max_video_seconds", 600, "MAX_VIDEO_SECONDS")
MAX_UPLOAD_BYTES = limit("uploads", "max_upload_mb", 500_000_000, "MAX_UPLOAD_BYTES", scale=1_000_000)
ASSET_MAX_COUNT = limit("uploads", "max_videos_per_user", 200, "ASSET_MAX_COUNT")
ASSET_MAX_TOTAL_BYTES = limit("uploads", "max_storage_gb_per_user", 20_000_000_000, "ASSET_MAX_TOTAL_BYTES", scale=1_000_000_000)

# Signed URLs are short-lived and never stored.
SIGNED_URL_TTL_SECONDS = int(os.getenv("SIGNED_URL_TTL_SECONDS", "3600"))
UPLOAD_URL_TTL_SECONDS = int(os.getenv("UPLOAD_URL_TTL_SECONDS", "3600"))

# Deletion: soft-delete the row, then a cleanup job removes the bytes after a grace period.
CLEANUP_GRACE_SECONDS = int(os.getenv("CLEANUP_GRACE_SECONDS", "600"))

# Worker queue behaviour.
JOB_MAX_ATTEMPTS = int(os.getenv("JOB_MAX_ATTEMPTS", "5"))
JOB_RETRY_BASE_SECONDS = int(os.getenv("JOB_RETRY_BASE_SECONDS", "30"))
WORKER_POLL_SECONDS = float(os.getenv("WORKER_POLL_SECONDS", "0.5"))
# A RUNNING job older than this was orphaned by a crashed/killed worker → requeue it.
# Must exceed the worst-case proxy encode (FFMPEG_TIMEOUT_SECONDS) plus download/upload slack.
WORKER_STALE_JOB_SECONDS = int(os.getenv("WORKER_STALE_JOB_SECONDS", "1800"))
WORKER_REAP_SECONDS = float(os.getenv("WORKER_REAP_SECONDS", "60"))
FFMPEG_TIMEOUT_SECONDS = int(os.getenv("FFMPEG_TIMEOUT_SECONDS", "1800"))
# Optional explicit folder containing ffmpeg/ffprobe (used when they aren't on the
# launching shell's PATH — e.g. a worker started before the PATH refresh).
FFMPEG_BIN_DIR = os.getenv("FFMPEG_BIN_DIR", "").strip().rstrip("/\\")
PROXY_LONGEST_SIDE = int(os.getenv("PROXY_LONGEST_SIDE", "1280"))

# Media pipeline validation.
PROXY_DURATION_TOLERANCE_S = 0.15

SUPABASE_READY = bool(SUPABASE_URL and SUPABASE_SECRET_KEY)
DB_READY = bool(DATABASE_URL)
