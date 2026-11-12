"""Runtime configuration for UrBG Remover.

Every setting is sourced from environment variables so the exact same image can
run locally, in Docker and on Railway without code changes.
"""

from __future__ import annotations

import os
import secrets
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

_TRUE = {"1", "true", "yes", "on", "y", "t"}
_FALSE = {"0", "false", "no", "off", "n", "f"}


def env_str(name: str, default: str | None = None, required: bool = False) -> str | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        if required:
            raise RuntimeError(f"Required environment variable '{name}' is missing.")
        return default
    return raw.strip()


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    return default


def env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(float(raw.strip()))
    except (TypeError, ValueError):
        warnings.warn(f"Environment variable '{name}' is not a valid integer, using default {default}.")
        return default


def env_list(name: str, default: List[str] | None = None) -> List[str]:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return list(default or [])
    return [item.strip() for item in raw.split(",") if item.strip()]


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    """Immutable snapshot of the application configuration."""

    app_name: str
    environment: str
    version: str

    # --- Admin credentials -------------------------------------------------
    admin_username: str
    admin_password: str
    admin_password_hash: str | None
    secret_key: str

    # --- Storage -----------------------------------------------------------
    data_dir: Path
    model_dir: Path
    db_path: Path

    # --- Limits ------------------------------------------------------------
    max_upload_mb: int
    max_dimension: int
    max_upload_bytes: int

    # --- Sessions / security ----------------------------------------------
    session_max_age_minutes: int
    session_cookie_name: str
    cookie_secure: bool
    cookie_samesite: str
    csrf_protect: bool
    login_max_attempts: int
    login_window_seconds: int
    login_lockout_seconds: int
    api_rate_limit_per_minute: int

    # --- AI engine ---------------------------------------------------------
    rembg_model: str
    rembg_provider: str
    engine_warmup_on_start: bool
    engine_timeout_seconds: int

    # --- Networking --------------------------------------------------------
    cors_origins: List[str] = field(default_factory=list)
    public_base_url: str = ""

    @property
    def is_production(self) -> bool:
        return self.environment.lower() in {"production", "prod"}

    @property
    def session_max_age_seconds(self) -> int:
        return self.session_max_age_minutes * 60

    @classmethod
    def from_env(cls) -> "Settings":
        environment = (env_str("ENVIRONMENT", "development") or "development").lower()

        data_dir = Path(env_str("DATA_DIR", str(PROJECT_ROOT / "data"))).expanduser()
        model_dir = Path(env_str("MODEL_DIR", str(PROJECT_ROOT / "models"))).expanduser()
        db_path = Path(env_str("DB_PATH", str(data_dir / "urbg.db"))).expanduser()

        admin_username = env_str("ADMIN_USERNAME", "Arafat") or "Arafat"
        admin_password = env_str("ADMIN_PASSWORD", "") or ""
        admin_password_hash = env_str("ADMIN_PASSWORD_HASH", "") or ""

        secret_key = env_str("SECRET_KEY", "") or ""
        if not secret_key:
            if environment in {"production", "prod"}:
                raise RuntimeError(
                    "SECRET_KEY must be set in production. Generate one with: "
                    "python -c \"import secrets; print(secrets.token_urlsafe(64))\""
                )
            secret_key = secrets.token_urlsafe(64)
            warnings.warn("SECRET_KEY is not set - generated an ephemeral key (sessions reset on restart).")

        max_upload_mb = max(1, env_int("MAX_UPLOAD_MB", 5))
        max_dimension = max(64, env_int("MAX_DIMENSION", 8000))

        cookie_secure = env_bool("COOKIE_SECURE", environment in {"production", "prod"})

        return cls(
            app_name=env_str("APP_NAME", "UrBG Remover") or "UrBG Remover",
            environment=environment,
            version=env_str("APP_VERSION", "1.0.0") or "1.0.0",
            admin_username=admin_username,
            admin_password=admin_password,
            admin_password_hash=admin_password_hash or None,
            secret_key=secret_key,
            data_dir=data_dir,
            model_dir=model_dir,
            db_path=db_path,
            max_upload_mb=max_upload_mb,
            max_dimension=max_dimension,
            max_upload_bytes=max_upload_mb * 1024 * 1024,
            session_max_age_minutes=max(1, env_int("SESSION_MAX_AGE_MINUTES", 480)),
            session_cookie_name=env_str("SESSION_COOKIE_NAME", "urbg_session") or "urbg_session",
            cookie_secure=cookie_secure,
            cookie_samesite=(env_str("COOKIE_SAMESITE", "lax") or "lax").lower(),
            csrf_protect=env_bool("CSRF_PROTECT", True),
            login_max_attempts=max(1, env_int("LOGIN_MAX_ATTEMPTS", 5)),
            login_window_seconds=max(30, env_int("LOGIN_WINDOW_SECONDS", 900)),
            login_lockout_seconds=max(0, env_int("LOGIN_LOCKOUT_SECONDS", 900)),
            api_rate_limit_per_minute=max(0, env_int("API_RATE_LIMIT_PER_MINUTE", 0)),
            rembg_model=env_str("REMBG_MODEL", "u2netp") or "u2netp",
            rembg_provider=env_str("REMBG_PROVIDER", "CPUExecutionProvider") or "CPUExecutionProvider",
            engine_warmup_on_start=env_bool("ENGINE_WARMUP_ON_START", True),
            engine_timeout_seconds=max(5, env_int("ENGINE_TIMEOUT_SECONDS", 120)),
            cors_origins=env_list("CORS_ORIGINS", []),
            public_base_url=(env_str("PUBLIC_BASE_URL", "") or "").rstrip("/"),
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
        _settings.ensure_directories()
    return _settings


def reset_settings() -> None:
    """Testing helper - force the settings singleton to be rebuilt."""
    global _settings
    _settings = None
