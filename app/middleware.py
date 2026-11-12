"""Custom ASGI middleware."""

from __future__ import annotations

import time
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .services import keys as key_service

SOURCE_BY_PATH = {
    "/api/v1/remove": "upload",
    "/api/v1/remove/url": "url",
    "/api/v1/remove/base64": "base64",
    "/api/v1/remove/color": "color",
}


class ApiUsageMiddleware(BaseHTTPMiddleware):
    """Records every public API call (success and failure) for the statistics."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if not path.startswith("/api/v1/"):
            return await call_next(request)

        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - started) * 1000)
        status_code = response.status_code
        success = status_code < 400

        bytes_out = 0
        content_length = response.headers.get("content-length")
        if content_length and content_length.isdigit():
            bytes_out = int(content_length)

        bytes_in = 0
        declared = request.headers.get("content-length")
        if declared and declared.isdigit():
            bytes_in = int(declared)

        token = request.headers.get("x-api-key")
        if not token:
            authorization = request.headers.get("authorization", "")
            if authorization.lower().startswith("bearer "):
                token = authorization[7:].strip()

        key = key_service.find_active_key(token) if token else None

        key_service.record_request(
            api_key_id=key["id"] if key else None,
            key_label=key.get("name") if key else "unknown",
            endpoint=path,
            method=request.method,
            status_code=status_code,
            success=success,
            bytes_in=bytes_in,
            bytes_out=bytes_out,
            duration_ms=duration_ms,
            source=SOURCE_BY_PATH.get(path, "api"),
            error=None if success else "request_failed",
        )

        if key:
            key_service.touch_key(
                key["id"],
                bytes_in=bytes_in,
                bytes_out=bytes_out,
                processed_image=path.startswith("/api/v1/remove"),
            )

        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds a few conservative security headers to every response."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        return response
