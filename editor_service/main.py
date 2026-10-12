"""Editor API — separate process from the dubbing backend and the media service.

    python -m editor_service.main            (or: uvicorn editor_service.main:app --port 8030)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from . import db
from .config import ALLOWED_ORIGINS, DATABASE_URL, EDITOR_API_PORT, FAKE_PROVIDERS, check_providers
from .errors import EditorError
from .routes import router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("editor.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL must be set in .env (Supabase direct/session pooler).")
    check_providers()
    app.state.pool = await db.connect()
    log.info("editor service ready (fake providers: %s)", FAKE_PROVIDERS)
    yield
    await app.state.pool.close()


app = FastAPI(title="Vani Editor", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(router)


@app.exception_handler(EditorError)
async def editor_error(_: Request, e: EditorError):
    if e.http_status >= 500:
        log.error("%s: %s", e.code, e)
    return JSONResponse({"code": e.code, "message": str(e)}, status_code=e.http_status)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, e: RequestValidationError):
    first = e.errors()[0] if e.errors() else {}
    where = ".".join(str(x) for x in first.get("loc", ())[1:])
    msg = str(first.get("msg", "Invalid request.")).removeprefix("Value error, ")
    return JSONResponse({"code": "input_invalid", "message": f"{where}: {msg}" if where else msg,
                         "errors": jsonable(e.errors())}, status_code=422)


@app.exception_handler(ValueError)
async def value_error(_: Request, e: ValueError):
    return JSONResponse({"code": "input_invalid", "message": str(e)}, status_code=422)


def jsonable(errors: list) -> list:
    return [{k: (v if isinstance(v, (str, int, float, list, type(None))) else str(v)) for k, v in err.items()} for err in errors]


@app.get("/api/editor/health")
async def health():
    pool: asyncpg.Pool = app.state.pool
    await db.ping(pool)
    return {"ok": True, "service": "editor", "fake_providers": FAKE_PROVIDERS}


def run() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=EDITOR_API_PORT)


if __name__ == "__main__":
    run()
