"""Supabase clients. The admin client uses the secret key (bypasses RLS) and is only ever
used server-side. Sign-in uses a fresh publishable-key client per call so one user's
session can never leak into another request."""

from __future__ import annotations

from functools import lru_cache

from supabase import Client, create_client

from .config import SUPABASE_PUBLISHABLE_KEY, SUPABASE_SECRET_KEY, SUPABASE_URL


@lru_cache(maxsize=1)
def admin() -> Client:
    if not (SUPABASE_URL and SUPABASE_SECRET_KEY):
        raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY must be set in .env.")
    return create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)


def public_client() -> Client:
    return create_client(SUPABASE_URL, SUPABASE_PUBLISHABLE_KEY)
