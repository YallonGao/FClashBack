"""Application entry point.

    uvicorn app.main:app --host 0.0.0.0 --port 8780
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI

from .config import get_settings
from .db import init_db
from .routers import auth, devices, sync

log = logging.getLogger("fclash")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if settings.uses_dev_secret:
        log.warning(
            "FCLASH_JWT_SECRET is unset; the development secret is in use. "
            "Set it before exposing this server."
        )
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title="FClash Sync",
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/docs",
        openapi_url="/openapi.json",
    )
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(devices.router, prefix="/api/v1")
    app.include_router(sync.router, prefix="/api/v1")

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
