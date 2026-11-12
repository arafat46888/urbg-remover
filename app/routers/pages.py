"""HTML pages (login + dashboard)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from ..dependencies import current_session, require_admin_page

router = APIRouter(tags=["pages"])

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@router.get("/", include_in_schema=False)
async def dashboard(request: Request) -> Response:
    """Serve the admin dashboard (protected by the session cookie)."""
    redirect = require_admin_page(request)
    if redirect is not None:
        return redirect
    return FileResponse(
        STATIC_DIR / "index.html",
        headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"},
    )


@router.get("/login", include_in_schema=False)
async def login_page(request: Request) -> Response:
    """Serve the login page."""
    if current_session(request) is not None:
        return RedirectResponse("/", status_code=302)
    return FileResponse(
        STATIC_DIR / "login.html",
        headers={"Cache-Control": "no-store", "X-Frame-Options": "DENY"},
    )


@router.get("/favicon.svg", include_in_schema=False)
async def favicon() -> Response:
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">'
        '<rect width="64" height="64" rx="14" fill="#0b0f16"/>'
        '<path d="M32 12 51 24v16L32 52 13 40V24z" fill="none" stroke="#38bdf8" stroke-width="4"/>'
        '<circle cx="32" cy="32" r="7" fill="#38bdf8"/></svg>'
    )
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/favicon.ico", include_in_schema=False)
async def favicon_ico() -> Response:
    return RedirectResponse("/favicon.svg", status_code=307)
