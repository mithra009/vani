"""Accounts: sign-up, sign-in (username or email), and verifying Supabase access tokens.

Tokens are ES256 JWTs signed by Supabase Auth; they're verified locally against the
project's JWKS (cached), so checking a request costs no network call."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Annotated

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, field_validator

from . import supa
from .config import AUTH_DISABLED, SUPABASE_JWKS_URL

log = logging.getLogger("vani.auth")
router = APIRouter(prefix="/api/auth")

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,28}[a-z0-9]$")
_jwks = jwt.PyJWKClient(SUPABASE_JWKS_URL, cache_keys=True, lifespan=3600) if SUPABASE_JWKS_URL.startswith("http") else None

TEST_USER = {"id": "00000000-0000-0000-0000-000000000001", "username": "tester", "email": "tester@example.com"}


# ---------------------------------------------------------------- token check

def _token(request: Request) -> str | None:
    h = request.headers.get("authorization", "")
    if h.lower().startswith("bearer "):
        return h[7:].strip()
    # <video src>, <a download> and EventSource can't send headers, so they pass it here.
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


# ---------------------------------------------------------------- sign-up / sign-in

class SignUp(BaseModel):
    username: str
    first_name: str
    last_name: str
    email: EmailStr
    password: str

    @field_validator("username")
    @classmethod
    def _u(cls, v: str) -> str:
        v = v.strip().lower()
        if not USERNAME_RE.match(v):
            raise ValueError("Username must be 3–30 characters: lowercase letters, numbers, - or _, "
                             "starting and ending with a letter or number.")
        return v

    @field_validator("first_name", "last_name")
    @classmethod
    def _n(cls, v: str) -> str:
        v = " ".join(v.split())
        if not 1 <= len(v) <= 60:
            raise ValueError("Names must be 1–60 characters.")
        return v

    @field_validator("password")
    @classmethod
    def _p(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters.")
        if len(v) > 72:
            raise ValueError("Password must be at most 72 characters.")
        return v


class SignIn(BaseModel):
    identifier: str      # username or email
    password: str


def _session(res) -> dict:
    s = res.session
    return {"access_token": s.access_token, "refresh_token": s.refresh_token, "expires_at": s.expires_at}


def _profile(user_id: str) -> dict | None:
    r = supa.admin().table("users").select("id, username, first_name, last_name, email, created_at") \
        .eq("id", user_id).limit(1).execute()
    return r.data[0] if r.data else None


@router.get("/username-available")
def username_available(username: str):
    u = username.strip().lower()
    if not USERNAME_RE.match(u):
        return {"available": False, "reason": "invalid"}
    r = supa.admin().table("users").select("id").eq("username", u).limit(1).execute()
    return {"available": not r.data}


@router.post("/signup")
def signup(body: SignUp):
    db = supa.admin()
    email = body.email.lower()
    if db.table("users").select("id").eq("username", body.username).limit(1).execute().data:
        raise HTTPException(409, "That username is taken.")
    if db.table("users").select("id").eq("email", email).limit(1).execute().data:
        raise HTTPException(409, "An account with that email already exists. Sign in instead.")
    try:
        created = db.auth.admin.create_user({
            "email": email, "password": body.password, "email_confirm": True,
            "user_metadata": {"username": body.username, "first_name": body.first_name, "last_name": body.last_name},
        })
    except Exception as e:
        msg = str(e)
        if "already" in msg.lower() and "registered" in msg.lower():
            raise HTTPException(409, "An account with that email already exists. Sign in instead.")
        if "password" in msg.lower():
            raise HTTPException(400, msg)
        log.error("create_user failed: %s", msg)
        raise HTTPException(502, "Couldn't create the account. Try again.")
    uid = created.user.id
    try:
        db.table("users").insert({
            "id": uid, "username": body.username, "first_name": body.first_name,
            "last_name": body.last_name, "email": email,
        }).execute()
    except Exception as e:
        # Keep auth.users and public.users consistent: undo the auth account.
        db.auth.admin.delete_user(uid)
        log.error("profile insert failed: %s", e)
        raise HTTPException(409, "That username or email was just taken. Try another.")
    res = supa.public_client().auth.sign_in_with_password({"email": email, "password": body.password})
    return {"session": _session(res), "user": _profile(uid)}


@router.post("/signin")
def signin(body: SignIn):
    ident = body.identifier.strip().lower()
    email = ident
    if "@" not in ident:
        r = supa.admin().table("users").select("email").eq("username", ident).limit(1).execute()
        if not r.data:
            raise HTTPException(401, "Wrong username, email or password.")
        email = r.data[0]["email"]
    try:
        res = supa.public_client().auth.sign_in_with_password({"email": email, "password": body.password})
    except Exception:
        raise HTTPException(401, "Wrong username, email or password.")
    return {"session": _session(res), "user": _profile(res.user.id)}


me_router = APIRouter(prefix="/api")


@me_router.get("/me")
async def me(user: User):
    if AUTH_DISABLED:
        return {**TEST_USER, "first_name": "Test", "last_name": "User"}
    p = await asyncio.to_thread(_profile, user["id"])
    if not p:
        raise HTTPException(404, "Your profile is missing. Sign up again or contact support.")
    return p
