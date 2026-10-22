"""Supplier Management — FastAPI application entrypoint."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app import config
from app.database import init_db
from app.routers import admin, api, auth, search, suppliers


@asynccontextmanager
async def lifespan(_app: FastAPI):
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


app = FastAPI(
    title="Supplier Management",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=config.SECRET_KEY,
    session_cookie=config.SESSION_COOKIE,
    https_only=False,
    same_site="lax",
    max_age=config.SESSION_MAX_AGE,
)
app.mount("/static", StaticFiles(directory=str(config.BASE_DIR / "static")), name="static")

app.include_router(auth.router)
app.include_router(suppliers.router)
app.include_router(search.router)
app.include_router(admin.router)
app.include_router(api.router)
