"""UrBG Remover - FastAPI application factory."""

from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from .config import get_settings
from .database import init_db
from .dependencies import session_middleware_kwargs
from .errors import register_exception_handlers
from .middleware import ApiUsageMiddleware, SecurityHeadersMiddleware
from .routers import admin, api, pages, public
from .services.admin_auth import sync_admin_password

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("urbg")

STATIC_DIR = Path(__file__).resolve().parent / "static"


def _warmup_engine() -> None:
    """Load the ONNX model in the background so the service starts quickly."""
    from .services.ai_engine import get_engine

    engine = get_engine()
    try:
        status = engine.warmup()
        if status.get("ready"):
            logger.info("AI engine ready (model=%s, load=%sms)", status.get("model"), status.get("load_ms"))
        else:
            logger.error("AI engine failed to load: %s", status.get("error"))
    except Exception as exc:  # pragma: no cover - depends on the environment
        logger.error("AI engine warmup failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.ensure_directories()

    init_db()
    sync_admin_password()
    logger.info(
        "UrBG Remover %s starting (env=%s, data=%s)",
        settings.version,
        settings.environment,
        settings.data_dir,
    )

    if settings.engine_warmup_on_start:
        threading.Thread(target=_warmup_engine, name="urbg-engine-warmup", daemon=True).start()

    yield

    logger.info("UrBG Remover shutting down")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version=settings.version,
        description=(
            "Self-hosted AI background removal API with a private admin dashboard. "
            "Remove backgrounds from JPG, PNG and WebP images with the rembg ONNX engine."
        ),
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    register_exception_handlers(app)
    app.add_middleware(SessionMiddleware, **session_middleware_kwargs())
    app.add_middleware(ApiUsageMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            allow_headers=["*"],
        )

    app.include_router(public.router)
    app.include_router(api.router)
    app.include_router(admin.router)
    app.include_router(pages.router)

    if STATIC_DIR.exists():
        app.mount("/assets", StaticFiles(directory=str(STATIC_DIR)), name="assets")

    return app


app = create_app()
