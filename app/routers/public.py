"""Public (unauthenticated) endpoints."""

from __future__ import annotations

import time

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..config import get_settings
from ..services.ai_engine import get_engine

router = APIRouter(tags=["public"])


@router.get("/health", summary="Health check")
async def health() -> JSONResponse:
    """Lightweight health check used by Railway and uptime monitors."""
    settings = get_settings()
    engine = get_engine()
    engine_status = engine.status()
    healthy = engine_status.get("error") is None
    payload = {
        "status": "ok" if healthy else "degraded",
        "service": settings.app_name,
        "version": settings.version,
        "uptime_seconds": int(time.monotonic() - _START_TIME),
        "engine": {
            "model": engine_status.get("model"),
            "ready": bool(engine_status.get("ready")),
            "error": engine_status.get("error"),
        },
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return JSONResponse(status_code=200 if healthy else 503, content=payload)


_START_TIME = time.monotonic()
