"""Verifying Supabase access tokens — same contract as the main backend:
Authorization: Bearer <jwt>  (or ?access_token= for <video src>/EventSource)."""

from __future__ import annotations

from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Request

from .config import AUTH_DISABLED, SUPABASE_JWKS_URL

TEST_USER = {"id": "00000000-0000-0000-0000-000000000001", "email": "tester@example.com"}

_jwks = (
    jwt.PyJWKClient(SUPABASE_JWKS_URL, cache_keys=True, lifespan=3600)
    if SUPABASE_JWKS_URL.startswith("http")
    else None
)


def _token(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    return request.query_params.get("access_token")


def verify(token: str) -> dict:
    if _jwks is None:
        raise HTTPException(500, "Sign-in isn't configured on the server (SUPABASE_JWKS_URL).")
    try:
        key = _jwks.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["ES256", "RS256"], audience="authenticated")
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Your session expired. Sign in again.")
    except jwt.PyJWTError:
        raise HTTPException(401, "You're not signed in.")
    return {"id": claims["sub"], "email": claims.get("email")}


def current_user(request: Request) -> dict:
    if AUTH_DISABLED:
        return TEST_USER
    token = _token(request)
    if not token:
        raise HTTPException(401, "You're not signed in.")
    return verify(token)


User = Annotated[dict, Depends(current_user)]
