"""Public REST API (v1).

Usage accounting is handled by :class:`app.middleware.ApiUsageMiddleware`, so
the handlers below only focus on processing and returning the result.
"""

from __future__ import annotations

import base64
import time
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from ..config import get_settings
from ..dependencies import require_api_key
from ..errors import APIError
from ..schemas import (
    ProcessOptions,
    RemoveBase64Request,
    RemoveColorRequest,
    RemoveUrlRequest,
)
from ..services import fetcher, keys as key_service
from ..services.ai_engine import EngineError, EngineUnavailable
from ..services.image_utils import ImageValidationError, decode_data_url
from ..services.multipart import MultipartError, parse_multipart, pick_file
from ..services.processor import ProcessResult, remove_background, remove_color_background
from ..services.runtime import get_runtime_settings

router = APIRouter(prefix="/api/v1", tags=["api"])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def read_body(request: Request, max_bytes: int) -> bytes:
    """Read the request body with a hard size limit."""
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > max_bytes:
        raise APIError(
            413,
            "file_too_large",
            f"The upload exceeds the {max_bytes // (1024 * 1024)} MB limit.",
        )
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise APIError(
                413,
                "file_too_large",
                f"The upload exceeds the {max_bytes // (1024 * 1024)} MB limit.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def options_from_query(request: Request) -> ProcessOptions:
    """Build processing options from the query string."""
    params = request.query_params
    data: dict[str, Any] = {}
    if "format" in params:
        data["output_format"] = params["format"]
    if "response_format" in params:
        data["response_format"] = params["response_format"]
    if "alpha_matting" in params:
        data["alpha_matting"] = params["alpha_matting"].lower() in {"1", "true", "yes", "on"}
    if "post_process_mask" in params:
        data["post_process_mask"] = params["post_process_mask"].lower() in {"1", "true", "yes", "on"}
    if "only_mask" in params:
        data["only_mask"] = params["only_mask"].lower() in {"1", "true", "yes", "on"}
    if "bgcolor" in params:
        data["bgcolor"] = params["bgcolor"]
    if "quality" in params:
        try:
            data["quality"] = int(params["quality"])
        except ValueError:
            pass
    try:
        return ProcessOptions(**data)
    except Exception as exc:
        raise APIError(422, "validation_error", str(exc)) from exc


def build_response(result: ProcessResult, options: ProcessOptions) -> Response:
    """Return either the raw image bytes or a JSON payload with base64."""
    headers = {
        "X-Process-Time-Ms": str(result.duration_ms),
        "X-Image-Width": str(result.input_info.width),
        "X-Image-Height": str(result.input_info.height),
        "Cache-Control": "no-store",
    }
    if options.response_format == "json":
        payload = {
            "success": True,
            "data": {
                "format": result.output_format,
                "content_type": result.content_type,
                "base64": base64.b64encode(result.data).decode("ascii"),
                "size_bytes": len(result.data),
                "duration_ms": result.duration_ms,
            },
            "input": result.input_info.as_dict(),
        }
        return JSONResponse(content=payload, headers=headers)
    return Response(content=result.data, media_type=result.content_type, headers=headers)


def handle_processing_error(exc: Exception) -> APIError:
    if isinstance(exc, ImageValidationError):
        return APIError(400, exc.code, exc.message)
    if isinstance(exc, EngineUnavailable):
        return APIError(503, "engine_unavailable", str(exc))
    if isinstance(exc, EngineError):
        return APIError(500, "processing_failed", str(exc))
    if isinstance(exc, MultipartError):
        return APIError(400, "invalid_multipart", str(exc))
    return APIError(500, "processing_failed", "The image could not be processed.")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.get("/status", summary="API and AI engine status")
async def status(request: Request, key: dict[str, Any] = Depends(require_api_key)) -> dict[str, Any]:
    from ..services.ai_engine import get_engine

    settings = get_settings()
    engine = get_engine()
    return {
        "success": True,
        "service": settings.app_name,
        "version": settings.version,
        "environment": settings.environment,
        "engine": engine.status(),
        "limits": {
            "max_upload_mb": settings.max_upload_mb,
            "max_dimension": settings.max_dimension,
            "allowed_formats": ["jpg", "jpeg", "png", "webp"],
        },
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


@router.post("/remove", summary="Remove the background of an uploaded image")
async def remove(
    request: Request,
    key: dict[str, Any] = Depends(require_api_key),
) -> Response:
    runtime = get_runtime_settings()
    options = options_from_query(request)

    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        body = await read_body(request, runtime.max_upload_bytes + 64 * 1024)
        _fields, files = parse_multipart(
            body, content_type, max_bytes=runtime.max_upload_bytes
        )
        raw = pick_file(files, "file", "image", "upload") or b""
        if not raw:
            raise APIError(
                400, "invalid_image", "No image was uploaded. Use the 'file' form field."
            )
    else:
        raw = await read_body(request, runtime.max_upload_bytes)
        if not raw:
            raise APIError(400, "invalid_image", "The request body is empty.")

    try:
        result = remove_background(raw, options)
    except Exception as exc:
        raise handle_processing_error(exc) from exc

    return build_response(result, options)


@router.post("/remove/url", summary="Remove the background of a remote image")
async def remove_url(
    payload: RemoveUrlRequest,
    request: Request,
    key: dict[str, Any] = Depends(require_api_key),
) -> Response:
    runtime = get_runtime_settings()
    raw, _content_type = fetcher.fetch_image(payload.url, max_bytes=runtime.max_upload_bytes)
    try:
        result = remove_background(raw, payload)
    except Exception as exc:
        raise handle_processing_error(exc) from exc
    return build_response(result, payload)


@router.post("/remove/base64", summary="Remove the background of a base64 image")
async def remove_base64(
    payload: RemoveBase64Request,
    request: Request,
    key: dict[str, Any] = Depends(require_api_key),
) -> Response:
    runtime = get_runtime_settings()
    raw = decode_data_url(payload.image)
    if len(raw) > runtime.max_upload_bytes:
        raise APIError(
            413,
            "file_too_large",
            f"The decoded image exceeds the {runtime.max_upload_mb} MB limit.",
        )
    try:
        result = remove_background(raw, payload)
    except Exception as exc:
        raise handle_processing_error(exc) from exc
    return build_response(result, payload)


@router.post("/remove/color", summary="Remove a solid background colour")
async def remove_color(
    payload: RemoveColorRequest,
    request: Request,
    key: dict[str, Any] = Depends(require_api_key),
) -> Response:
    runtime = get_runtime_settings()
    if payload.image:
        raw = decode_data_url(payload.image)
    elif payload.url:
        raw, _content_type = fetcher.fetch_image(payload.url, max_bytes=runtime.max_upload_bytes)
    else:
        raise APIError(
            422, "validation_error", "Either 'image' (base64) or 'url' must be supplied."
        )

    if len(raw) > runtime.max_upload_bytes:
        raise APIError(
            413,
            "file_too_large",
            f"The decoded image exceeds the {runtime.max_upload_mb} MB limit.",
        )

    try:
        result = remove_color_background(
            raw,
            payload.color,
            tolerance=payload.tolerance,
            softness=payload.softness,
            options=payload,
        )
    except Exception as exc:
        raise handle_processing_error(exc) from exc
    return build_response(result, payload)


@router.get("/usage", summary="Usage statistics for the calling API key")
async def usage(
    request: Request,
    days: int = 30,
    key: dict[str, Any] = Depends(require_api_key),
) -> dict[str, Any]:
    days = max(1, min(365, days))
    series = key_service.usage_timeseries(days)
    return {
        "success": True,
        "key": {
            "id": key["id"],
            "name": key.get("name"),
            "created_at": key.get("created_at"),
            "last_used_at": key.get("last_used_at"),
            "revoked": bool(key.get("revoked")),
        },
        "totals": {
            "requests": int(key.get("request_count") or 0),
            "images_processed": int(key.get("image_count") or 0),
            "bytes_in": int(key.get("bytes_in") or 0),
            "bytes_out": int(key.get("bytes_out") or 0),
        },
        "period": {
            "days": days,
            "requests": sum(point["requests"] for point in series),
            "success": sum(point["success"] for point in series),
            "failed": sum(point["failed"] for point in series),
            "bytes_out": sum(point["bytes_out"] for point in series),
        },
        "daily": series,
    }
