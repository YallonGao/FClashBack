"""Application entry point.

    uvicorn app.main:app --host 0.0.0.0 --port 8780
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import BASE_DIR, get_settings
from .db import init_db
from .routers import auth, devices, subscriptions, sync

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
    app.include_router(subscriptions.router, prefix="/api/v1")

    @app.get("/healthz", tags=["meta"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    _mount_console(app)
    return app


def _mount_console(app: FastAPI) -> None:
    """Serve the built console from the same origin when it is present.

    One process and one certificate is what makes the console usable on a
    small server; an empty directory simply leaves the API-only deployment
    it had before. The catch-all is registered last so the API routes win.
    """

    directory = Path(os.getenv("FCLASH_FRONTEND_DIR", str(BASE_DIR / "frontend")))
    index = directory / "index.html"
    if not index.is_file():
        return
    assets = directory / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="console-assets")

    @app.get("/{path:path}", include_in_schema=False)
    def console(path: str) -> FileResponse:
        candidate = (directory / path).resolve()
        if path and candidate.is_file() and directory.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
