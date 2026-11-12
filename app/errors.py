"""JSON error envelope and FastAPI exception handlers."""

from __future__ import annotations

import logging
import traceback
from typing import Any, Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger("urbg.errors")


class APIError(Exception):
    """Application error carrying an HTTP status code and machine readable code."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers or {}

    def to_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content={"error": {"code": self.code, "message": self.message, "details": self.details}},
            headers=self.headers or None,
        )


def error_payload(code: str, message: str, details: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api_error(_: Request, exc: APIError) -> JSONResponse:
        return exc.to_response()

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "error" in detail:
            return JSONResponse(status_code=exc.status_code, content=detail, headers=exc.headers)
        code = {
            400: "bad_request",
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            413: "payload_too_large",
            415: "unsupported_media_type",
            429: "rate_limited",
            500: "internal_error",
            503: "service_unavailable",
        }.get(exc.status_code, "error")
        return JSONResponse(
            status_code=exc.status_code,
            content=error_payload(code, str(detail)),
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=error_payload(
                "validation_error",
                "The request body or parameters are invalid.",
                {"errors": _jsonable_errors(exc.errors())},
            ),
        )

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled error: %s\n%s", exc, traceback.format_exc())
        return JSONResponse(
            status_code=500,
            content=error_payload("internal_error", "An unexpected error occurred."),
        )


def _jsonable_errors(errors: list[dict[str, Any]]) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    for err in errors:
        item = {k: v for k, v in err.items() if k != "ctx"}
        item["loc"] = [str(part) for part in err.get("loc", [])]
        cleaned.append(item)
    return cleaned
