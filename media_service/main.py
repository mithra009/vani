"""Media library API — separate process from the dubbing backend.

    python -m media_service.main            (or: uvicorn media_service.main:app --port 8020)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .config import ALLOWED_ORIGINS, DATABASE_URL, MEDIA_API_PORT, SUPABASE_READY
from .routes import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("media.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL must be set in .env (Supabase direct/session pooler).")
    app.state.pool = await db.connect()
    log.info("media service ready (bucket configured: %s)", SUPABASE_READY)
    yield
    await app.state.pool.close()


app = FastAPI(title="Vani Media", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.get("/api/health")
async def health():
    pool: asyncpg.Pool = app.state.pool
    await db.ping(pool)
    return {"ok": True, "service": "media"}


def run() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=MEDIA_API_PORT)


if __name__ == "__main__":
    run()
