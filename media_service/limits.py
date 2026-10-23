"""Reads config/limits.toml, the single file for app-side limits (shared by media_service and
editor_service). Precedence: environment variable > limits.toml > the default given here.

A missing file is fine (defaults apply). A malformed file stops the service at import with the
file name and the problem, rather than running with limits nobody chose.
"""

from __future__ import annotations

import os
import tomllib
from pathlib import Path

LIMITS_FILE = Path(os.getenv("VANI_LIMITS_FILE", Path(__file__).resolve().parents[1] / "config" / "limits.toml"))


def _load() -> dict:
    if not LIMITS_FILE.exists():
        return {}
    try:
        return tomllib.loads(LIMITS_FILE.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise RuntimeError(f"{LIMITS_FILE} is not valid TOML: {e}") from e


_FILE = _load()


def limit(section: str, key: str, default: int, env: str | None = None, scale: int = 1) -> int:
    """One limit, as an int. `scale` converts file units (MB/GB) to the env var's units (bytes)."""
    if env and os.getenv(env, "").strip():
        return int(os.environ[env])
    value = _FILE.get(section, {}).get(key)
    if value is None:
        return default
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0:
        raise RuntimeError(f"{LIMITS_FILE}: [{section}] {key} must be a non-negative number, got {value!r}")
    return int(value * scale)
