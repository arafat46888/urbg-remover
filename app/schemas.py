"""Pydantic request/response models."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class LoginRequest(BaseModel):
    username: str = Field(default="", max_length=120)
    password: str = Field(default="", max_length=256)


class LogoutResponse(BaseModel):
    success: bool = True
    message: str = "Signed out"


class ProcessOptions(BaseModel):
    """Shared processing options for every removal endpoint."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    alpha_matting: bool = Field(
        default=False, description="Run alpha matting for softer, more accurate edges."
    )
    alpha_matting_foreground_threshold: int = Field(default=240, ge=0, le=255)
    alpha_matting_background_threshold: int = Field(default=10, ge=0, le=255)
    alpha_matting_erode_size: int = Field(default=10, ge=0, le=64)
    post_process_mask: bool = Field(
        default=False, description="Refine the mask with a guided filter."
    )
    only_mask: bool = Field(default=False, description="Return the mask instead of a cutout.")
    bgcolor: Optional[str] = Field(
        default=None, description="Optional hex background colour (e.g. #ffffff)."
    )
    output_format: str = Field(
        default="png", alias="format", description="Output image format: png, webp or jpeg."
    )
    response_format: str = Field(
        default="binary", description="binary (default) or json (base64 payload)."
    )
    quality: int = Field(default=92, ge=40, le=100)

    @field_validator("output_format")
    @classmethod
    def _validate_format(cls, value: str) -> str:
        value = (value or "png").strip().lower()
        if value in {"jpg"}:
            value = "jpeg"
        if value not in {"png", "webp", "jpeg"}:
            raise ValueError("format must be one of: png, webp, jpeg")
        return value

    @field_validator("response_format")
    @classmethod
    def _validate_response_format(cls, value: str) -> str:
        value = (value or "binary").strip().lower()
        if value not in {"binary", "json"}:
            raise ValueError("response_format must be either 'binary' or 'json'")
        return value

    @field_validator("bgcolor")
    @classmethod
    def _validate_bgcolor(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        if not value:
            return None
        if not value.startswith("#"):
            value = f"#{value}"
        if len(value) not in (4, 7):
            raise ValueError("bgcolor must be a hex colour such as #ffffff")
        int(value[1:], 16)
        return value.lower()


class RemoveUrlRequest(ProcessOptions):
    url: str = Field(min_length=4, max_length=2048)


class RemoveBase64Request(ProcessOptions):
    image: str = Field(min_length=8, max_length=32_000_000)


class RemoveColorRequest(ProcessOptions):
    color: str = Field(default="#ffffff", max_length=32)
    tolerance: int = Field(default=20, ge=0, le=100)
    softness: int = Field(default=10, ge=0, le=100)
    image: Optional[str] = Field(default=None, max_length=32_000_000)
    url: Optional[str] = Field(default=None, max_length=2048)

    @field_validator("color")
    @classmethod
    def _validate_color(cls, value: str) -> str:
        value = (value or "#ffffff").strip()
        if not value.startswith("#"):
            value = f"#{value}"
        if len(value) == 4:
            value = "#" + "".join(ch * 2 for ch in value[1:])
        if len(value) != 7:
            raise ValueError("color must be a hex colour such as #ffffff")
        int(value[1:], 16)
        return value.lower()


class CreateKeyRequest(BaseModel):
    name: str = Field(default="", max_length=80)


class KeyCreatedResponse(BaseModel):
    id: int
    name: str
    key: str
    prefix: str
    last4: str
    created_at: str
    warning: str = "Copy this key now - it will never be shown again."


class SettingsUpdateRequest(BaseModel):
    max_upload_mb: Optional[int] = Field(default=None, ge=1, le=50)
    default_model: Optional[str] = Field(default=None, max_length=60)
    alpha_matting: Optional[bool] = None
    post_process_mask: Optional[bool] = None
    default_output_format: Optional[str] = Field(default=None, max_length=10)

    @field_validator("default_output_format")
    @classmethod
    def _validate_output_format(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip().lower()
        if value == "jpg":
            value = "jpeg"
        if value not in {"png", "webp", "jpeg"}:
            raise ValueError("default_output_format must be png, webp or jpeg")
        return value


class EngineModelRequest(BaseModel):
    model: str = Field(min_length=2, max_length=60)


class GenericResponse(BaseModel):
    success: bool = True
    message: str = ""


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    error: ErrorDetail
