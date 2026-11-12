"""Runtime (database backed) settings that can be changed from the dashboard."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..config import get_settings
from ..database import get_db

DEFAULT_MODEL = "u2netp"
AVAILABLE_MODELS = [
    {"id": "u2netp", "label": "u2netp (lightweight, 4.7 MB)"},
    {"id": "u2net", "label": "u2net (accurate, 176 MB)"},
    {"id": "u2net_human_seg", "label": "u2net_human_seg (portraits, 176 MB)"},
    {"id": "silueta", "label": "silueta (small, 44 MB)"},
    {"id": "isnet-general-use", "label": "isnet-general-use (accurate, 176 MB)"},
]


@dataclass(frozen=True)
class RuntimeSettings:
    max_upload_mb: int
    default_model: str
    alpha_matting: bool
    post_process_mask: bool
    default_output_format: str

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024

    def as_dict(self) -> dict[str, Any]:
        return {
            "max_upload_mb": self.max_upload_mb,
            "default_model": self.default_model,
            "alpha_matting": self.alpha_matting,
            "post_process_mask": self.post_process_mask,
            "default_output_format": self.default_output_format,
        }


def get_runtime_settings() -> RuntimeSettings:
    """Read the current runtime settings (falls back to the environment)."""
    settings = get_settings()
    stored = get_db().all_settings()

    def _int(key: str, default: int) -> int:
        try:
            return int(stored.get(key, default))
        except (TypeError, ValueError):
            return default

    def _bool(key: str, default: bool) -> bool:
        raw = stored.get(key)
        if raw is None:
            return default
        return str(raw).lower() in {"1", "true", "yes", "on"}

    model = stored.get("default_model") or settings.rembg_model or DEFAULT_MODEL
    output_format = (stored.get("default_output_format") or "png").lower()
    if output_format not in {"png", "webp", "jpeg"}:
        output_format = "png"

    return RuntimeSettings(
        max_upload_mb=max(1, min(50, _int("max_upload_mb", settings.max_upload_mb))),
        default_model=model,
        alpha_matting=_bool("alpha_matting", False),
        post_process_mask=_bool("post_process_mask", False),
        default_output_format=output_format,
    )


def update_runtime_settings(values: dict[str, Any]) -> RuntimeSettings:
    """Persist the provided runtime settings."""
    db = get_db()
    allowed = {
        "max_upload_mb",
        "default_model",
        "alpha_matting",
        "post_process_mask",
        "default_output_format",
    }
    for key, value in values.items():
        if key not in allowed or value is None:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        db.set_setting(key, str(value))
    return get_runtime_settings()
