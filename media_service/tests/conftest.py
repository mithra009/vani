"""Shared setup for media_service tests.

Ensures the repo root is importable and forces auth-off / offline settings before
any media_service module (which reads env at import time) is loaded.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ["VANI_AUTH_DISABLED"] = "1"
os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL_TEST", "")

import pytest  # noqa: E402
