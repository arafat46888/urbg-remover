"""Private admin API (session + CSRF protected)."""

from __future__ import annotations

import base64
import time
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from ..api_docs import ERROR_CODES, build_api_reference
from ..config import get_settings
from ..dependencies import (
    client_ip,
    current_session,
    destroy_session,
    get_login_throttle,
    issue_session,
    require_admin,
    require_csrf,
)
from ..errors import APIError
from ..integrations import build_integrations
from ..schemas import (
    CreateKeyRequest,
    EngineModelRequest,
    LoginRequest,
    SettingsUpdateRequest,
)
from ..services import admin_auth, keys as key_service
from ..services.ai_engine import EngineError, EngineUnavailable, get_engine
from ..services.image_utils import ImageValidationError
from ..services.multipart import MultipartError, parse_multipart, pick_file
from ..services.processor import remove_background
from ..services.runtime import (
    AVAILABLE_MODELS,
    get_runtime_settings,
    update_runtime_settings,
)

router = APIRouter(prefix="/admin/api", tags=["admin"])


def base_url_for(request: Request) -> str:
    """Public base URL of this deployment."""
    settings = get_settings()
    if settings.public_base_url:
        return settings.public_base_url
    return str(request.base_url).rstrip("/")


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------
@router.post("/login", summary="Sign in to the dashboard")
async def login(payload: LoginRequest, request: Request) -> JSONResponse:
    settings = get_settings()
    throttle = get_login_throttle()
    identifier = f"{client_ip(request)}|{(payload.username or '').strip().lower()}"

    locked, retry_after = throttle.is_locked(identifier)
    if locked:
        raise APIError(
            429,
            "too_many_attempts",
            "Too many failed login attempts. Please try again later.",
            {"retry_after": retry_after},
            headers={"Retry-After": str(retry_after)},
        )

    username_ok = (payload.username or "").strip() == settings.admin_username
    password_ok = admin_auth.verify_admin_password(payload.password or "")

    if not (username_ok and password_ok):
        failures = throttle.record_failure(identifier)
        remaining = max(0, settings.login_max_attempts - failures)
        raise APIError(
            401,
            "invalid_credentials",
            "Invalid username or password.",
            {"attempts_remaining": remaining},
        )

    throttle.reset(identifier)
    csrf = issue_session(request, settings.admin_username)
    return JSONResponse(
        content={
            "success": True,
            "username": settings.admin_username,
            "csrf_token": csrf,
            "expires_in": settings.session_max_age_seconds,
        }
    )


@router.post("/logout", summary="Sign out")
async def logout(
    request: Request,
    _csrf: None = Depends(require_csrf),
) -> JSONResponse:
    destroy_session(request)
    return JSONResponse(content={"success": True, "message": "Signed out"})


@router.get("/session", summary="Current session details")
async def session_info(request: Request) -> dict[str, Any]:
    session = current_session(request)
    if session is None:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "username": session.get("username"),
        "csrf_token": session.get("csrf"),
        "expires_at": session.get("expires_at"),
        "issued_at": session.get("issued_at"),
    }


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@router.get("/overview", summary="Dashboard overview")
async def overview(request: Request, session: dict = Depends(require_admin)) -> dict[str, Any]:
    engine = get_engine()
    stats = key_service.overview_stats()
    runtime = get_runtime_settings()
    settings = get_settings()
    return {
        "stats": stats,
        "engine": engine.status(),
        "runtime": runtime.as_dict(),
        "server": {
            "app_name": settings.app_name,
            "version": settings.version,
            "environment": settings.environment,
            "status": "online",
            "base_url": base_url_for(request),
        },
        "recent_requests": key_service.recent_requests(10),
    }


@router.post("/remove", summary="Remove a background from the dashboard")
async def dashboard_remove(
    request: Request,
    session: dict = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
) -> Response:
    """Process an image uploaded from the dashboard (no API key required)."""
    runtime = get_runtime_settings()
    started = time.perf_counter()
    raw = b""
    source = "dashboard"

    try:
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("multipart/form-data"):
            body = await _read_body(request, runtime.max_upload_bytes + 64 * 1024)
            _fields, files = parse_multipart(body, content_type, max_bytes=runtime.max_upload_bytes)
            raw = pick_file(files, "file", "image", "upload") or b""
        else:
            raw = await _read_body(request, runtime.max_upload_bytes)
        if not raw:
            raise APIError(400, "invalid_image", "No image was supplied.")

        options = _options_from_form(request.query_params, runtime)
        result = remove_background(raw, options)
    except APIError:
        raise
    except ImageValidationError as exc:
        raise APIError(400, exc.code, exc.message) from exc
    except MultipartError as exc:
        raise APIError(400, "invalid_multipart", str(exc)) from exc
    except EngineUnavailable as exc:
        raise APIError(503, "engine_unavailable", str(exc)) from exc
    except EngineError as exc:
        raise APIError(500, "processing_failed", str(exc)) from exc

    key_service.record_request(
        api_key_id=None,
        key_label="dashboard",
        endpoint="/admin/remove",
        method=request.method,
        status_code=200,
        success=True,
        bytes_in=len(raw),
        bytes_out=len(result.data),
        duration_ms=int((time.perf_counter() - started) * 1000),
        source=source,
    )

    return JSONResponse(
        content={
            "success": True,
            "image": base64.b64encode(result.data).decode("ascii"),
            "content_type": result.content_type,
            "duration_ms": result.duration_ms,
            "input": result.input_info.as_dict(),
        },
        headers={"X-Process-Time-Ms": str(result.duration_ms)},
    )


async def _read_body(request: Request, max_bytes: int) -> bytes:
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


def _options_from_form(params: Any, runtime: Any):
    from ..schemas import ProcessOptions

    data: dict[str, Any] = {
        "output_format": runtime.default_output_format,
        "alpha_matting": runtime.alpha_matting,
        "post_process_mask": runtime.post_process_mask,
    }
    if "format" in params:
        data["output_format"] = params["format"]
    if "alpha_matting" in params:
        data["alpha_matting"] = params["alpha_matting"].lower() in {"1", "true", "yes", "on"}
    if "post_process_mask" in params:
        data["post_process_mask"] = params["post_process_mask"].lower() in {"1", "true", "yes", "on"}
    if "only_mask" in params:
        data["only_mask"] = params["only_mask"].lower() in {"1", "true", "yes", "on"}
    if "bgcolor" in params:
        data["bgcolor"] = params["bgcolor"]
    try:
        return ProcessOptions(**data)
    except Exception as exc:
        raise APIError(422, "validation_error", str(exc)) from exc


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
@router.get("/keys", summary="List API keys")
async def list_keys(request: Request, session: dict = Depends(require_admin)) -> dict[str, Any]:
    return {"keys": key_service.list_keys()}


@router.post("/keys", summary="Create an API key")
async def create_key(
    payload: CreateKeyRequest,
    request: Request,
    session: dict = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
) -> dict[str, Any]:
    created = key_service.create_key(payload.name)
    return {
        "id": created["id"],
        "name": created["name"],
        "key": created["key"],
        "prefix": created["prefix"],
        "last4": created["last4"],
        "created_at": created["created_at"],
        "warning": "Copy this key now - it will never be shown again.",
    }


@router.post("/keys/{key_id}/revoke", summary="Revoke an API key")
async def revoke_key(
    key_id: int,
    request: Request,
    session: dict = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
) -> dict[str, Any]:
    if not key_service.revoke_key(key_id):
        raise APIError(404, "not_found", "The API key does not exist or is already revoked.")
    return {"success": True, "id": key_id}


@router.post("/keys/{key_id}/restore", summary="Restore a revoked API key")
async def restore_key(
    key_id: int,
    request: Request,
    session: dict = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
) -> dict[str, Any]:
    if key_service.get_key(key_id) is None:
        raise APIError(404, "not_found", "The API key does not exist.")
    key_service.restore_key(key_id)
    return {"success": True, "id": key_id}


@router.delete("/keys/{key_id}", summary="Delete an API key")
async def delete_key(
    key_id: int,
    request: Request,
    session: dict = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
) -> dict[str, Any]:
    if not key_service.delete_key(key_id):
        raise APIError(404, "not_found", "The API key does not exist.")
    return {"success": True, "id": key_id}


# ---------------------------------------------------------------------------
# Usage / statistics
# ---------------------------------------------------------------------------
@router.get("/usage", summary="Usage statistics")
async def usage(
    request: Request,
    days: int = 30,
    session: dict = Depends(require_admin),
) -> dict[str, Any]:
    days = max(1, min(365, days))
    return {
        "overview": key_service.overview_stats(),
        "daily": key_service.usage_timeseries(days),
        "endpoints": key_service.endpoint_breakdown(),
        "recent": key_service.recent_requests(30),
    }


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@router.get("/settings", summary="Read the dashboard settings")
async def read_settings(
    request: Request, session: dict = Depends(require_admin)
) -> dict[str, Any]:
    settings = get_settings()
    runtime = get_runtime_settings()
    engine = get_engine()
    return {
        "runtime": runtime.as_dict(),
        "available_models": AVAILABLE_MODELS,
        "environment": {
            "app_name": settings.app_name,
            "version": settings.version,
            "environment": settings.environment,
            "max_upload_mb": settings.max_upload_mb,
            "max_dimension": settings.max_dimension,
            "session_max_age_minutes": settings.session_max_age_minutes,
            "api_rate_limit_per_minute": settings.api_rate_limit_per_minute,
            "base_url": base_url_for(request),
        },
        "engine": engine.status(),
    }


@router.put("/settings", summary="Update the dashboard settings")
async def write_settings(
    payload: SettingsUpdateRequest,
    request: Request,
    session: dict = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
) -> dict[str, Any]:
    values = payload.model_dump(exclude_none=True)
    runtime = update_runtime_settings(values)
    if "default_model" in values:
        get_engine().set_model(runtime.default_model)
    return {"success": True, "runtime": runtime.as_dict()}


@router.post("/engine/warmup", summary="Pre-load the AI model")
async def warmup(
    request: Request,
    session: dict = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
) -> dict[str, Any]:
    status = get_engine().warmup()
    return {"success": bool(status.get("ready")), "engine": status}


@router.post("/engine/model", summary="Switch the AI model")
async def switch_model(
    payload: EngineModelRequest,
    request: Request,
    session: dict = Depends(require_admin),
    _csrf: None = Depends(require_csrf),
) -> dict[str, Any]:
    engine = get_engine()
    engine.set_model(payload.model)
    update_runtime_settings({"default_model": payload.model})
    status = engine.warmup()
    return {"success": bool(status.get("ready")), "engine": status}


# ---------------------------------------------------------------------------
# Documentation
# ---------------------------------------------------------------------------
@router.get("/docs", summary="API reference")
async def api_docs(request: Request, session: dict = Depends(require_admin)) -> dict[str, Any]:
    base = base_url_for(request)
    runtime = get_runtime_settings()
    return {
        "base_url": base,
        "endpoints": build_api_reference(base, runtime.max_upload_mb),
        "errors": ERROR_CODES,
    }


@router.get("/integrations", summary="Integration examples")
async def integrations(request: Request, session: dict = Depends(require_admin)) -> dict[str, Any]:
    base = base_url_for(request)
    return {"base_url": base, "integrations": build_integrations(base)}
