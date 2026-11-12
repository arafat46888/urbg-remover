"""Authentication dependencies for the admin dashboard and the public API."""

from __future__ import annotations

import secrets
import time
from typing import Any, Optional
from urllib.parse import urlencode

from fastapi import Header, Request
from fastapi.responses import RedirectResponse

from .config import get_settings
from .errors import APIError
from .security import LoginThrottle, SlidingWindowLimiter
from .services import keys as key_service

SESSION_KEY = "urbg_admin"

_api_limiter: Optional[SlidingWindowLimiter] = None
_login_throttle: Optional[LoginThrottle] = None


def get_api_limiter() -> SlidingWindowLimiter:
    """Per-API-key sliding window limiter (disabled when the limit is 0)."""
    global _api_limiter
    settings = get_settings()
    if _api_limiter is None:
        _api_limiter = SlidingWindowLimiter(settings.api_rate_limit_per_minute, 60)
    return _api_limiter


def get_login_throttle() -> LoginThrottle:
    """Failed-login tracker used to lock out brute force attempts."""
    global _login_throttle
    settings = get_settings()
    if _login_throttle is None:
        _login_throttle = LoginThrottle(
            settings.login_max_attempts,
            settings.login_window_seconds,
            settings.login_lockout_seconds,
        )
    return _login_throttle


def reset_login_throttle() -> None:
    global _login_throttle
    _login_throttle = None


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------
def client_ip(request: Request) -> str:
    """Best effort client IP (honouring a single proxy header)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


def bearer_token(request: Request, header_value: Optional[str]) -> Optional[str]:
    if header_value:
        return header_value.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


# ---------------------------------------------------------------------------
# Admin session
# ---------------------------------------------------------------------------
def issue_session(request: Request, username: str) -> str:
    """Create a fresh admin session and return its CSRF token."""
    settings = get_settings()
    now = int(time.time())
    csrf = secrets.token_urlsafe(32)
    request.session.clear()
    request.session[SESSION_KEY] = {
        "username": username,
        "role": "admin",
        "csrf": csrf,
        "issued_at": now,
        "expires_at": now + settings.session_max_age_seconds,
        "sid": secrets.token_urlsafe(16),
    }
    return csrf


def current_session(request: Request) -> Optional[dict[str, Any]]:
    """Return the active admin session, or ``None`` when absent/expired."""
    data = request.session.get(SESSION_KEY)
    if not isinstance(data, dict):
        return None
    expires_at = int(data.get("expires_at", 0))
    if expires_at and expires_at < int(time.time()):
        request.session.clear()
        return None
    return data


def destroy_session(request: Request) -> None:
    request.session.clear()


def require_admin(request: Request) -> dict[str, Any]:
    """Dependency for admin JSON endpoints."""
    session = current_session(request)
    if session is None:
        raise APIError(401, "admin_auth_required", "Administrator authentication is required.")
    return session


def require_csrf(request: Request, x_csrf_token: str = Header(default="")) -> None:
    """Validate the CSRF token for state-changing admin requests."""
    settings = get_settings()
    if not settings.csrf_protect:
        return
    session = current_session(request)
    if session is None:
        raise APIError(401, "admin_auth_required", "Administrator authentication is required.")
    expected = session.get("csrf", "")
    provided = (x_csrf_token or "").strip()
    if not expected or not provided or not secrets.compare_digest(expected, provided):
        raise APIError(403, "invalid_csrf_token", "The CSRF token is missing or invalid.")


def require_admin_page(request: Request) -> Optional[RedirectResponse]:
    """Guard HTML pages - returns a redirect response when not authenticated."""
    if current_session(request) is None:
        target = request.url.path
        if request.url.query:
            target = f"{target}?{request.url.query}"
        return RedirectResponse(
            f"/login?{urlencode({'next': target})}", status_code=302
        )
    return None


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
def require_api_key(
    request: Request,
    x_api_key: str = Header(default="", alias="X-API-Key"),
) -> dict[str, Any]:
    """Authenticate a public API request via ``X-API-Key`` (or Bearer token)."""
    settings = get_settings()
    token = bearer_token(request, x_api_key)
    if not token:
        raise APIError(
            401,
            "missing_api_key",
            "An API key is required. Send it in the X-API-Key header.",
        )

    record = key_service.find_active_key(token)
    if record is None:
        raise APIError(401, "invalid_api_key", "The supplied API key is invalid or revoked.")
    if record.get("revoked"):
        raise APIError(401, "revoked_api_key", "The supplied API key has been revoked.")

    if settings.api_rate_limit_per_minute > 0:
        limit = get_api_limiter().hit(f"key:{record['id']}")
        if not limit.allowed:
            raise APIError(
                429,
                "rate_limited",
                "Too many requests. Please slow down and try again shortly.",
                {"retry_after": limit.retry_after},
                headers={"Retry-After": str(limit.retry_after)},
            )

    return record


def api_key_context(record: dict[str, Any]) -> dict[str, Any]:
    """Helper describing which key was used (for logging)."""
    return {"api_key_id": record["id"], "key_label": record.get("name") or "api-key"}


def session_middleware_kwargs() -> dict[str, Any]:
    """Keyword arguments for Starlette's signed-cookie session middleware."""
    settings = get_settings()
    return {
        "secret_key": settings.secret_key,
        "session_cookie": settings.session_cookie_name,
        "max_age": settings.session_max_age_seconds,
        "same_site": settings.cookie_samesite,
        "https_only": settings.cookie_secure,
        "path": "/",
    }
