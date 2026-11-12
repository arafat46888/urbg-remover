"""Image processing pipeline shared by the public API and the dashboard."""

from __future__ import annotations

import io
import time
from dataclasses import dataclass
from typing import Any, Optional

from PIL import Image

from ..config import Settings, get_settings
from ..schemas import ProcessOptions
from . import image_utils
from .ai_engine import EngineError, EngineUnavailable, get_engine
from .image_utils import ImageInfo, ImageValidationError


@dataclass
class ProcessResult:
    data: bytes
    content_type: str
    input_info: ImageInfo
    duration_ms: int
    output_format: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "input": self.input_info.as_dict(),
            "output_format": self.output_format,
            "content_type": self.content_type,
            "size_bytes": len(self.data),
            "duration_ms": self.duration_ms,
        }


CONTENT_TYPES = {
    "png": "image/png",
    "webp": "image/webp",
    "jpeg": "image/jpeg",
}


def _load_and_validate(raw: bytes, settings: Settings) -> tuple[Image.Image, ImageInfo]:
    from .runtime import get_runtime_settings

    runtime = get_runtime_settings()
    image, info = image_utils.validate_upload(
        raw,
        max_bytes=runtime.max_upload_bytes,
        max_dimension=settings.max_dimension,
    )
    return image, info


def remove_background(
    raw: bytes,
    options: Optional[ProcessOptions] = None,
    *,
    settings: Optional[Settings] = None,
) -> ProcessResult:
    """Run the AI background removal pipeline."""
    settings = settings or get_settings()
    options = options or ProcessOptions()
    started = time.perf_counter()

    image, info = _load_and_validate(raw, settings)

    engine = get_engine()
    png_bytes = engine.remove(
        image_utils.to_png_bytes(image),
        alpha_matting=options.alpha_matting,
        alpha_matting_foreground_threshold=options.alpha_matting_foreground_threshold,
        alpha_matting_background_threshold=options.alpha_matting_background_threshold,
        alpha_matting_erode_size=options.alpha_matting_erode_size,
        post_process_mask=options.post_process_mask,
        only_mask=options.only_mask,
    )

    output = Image.open(io.BytesIO(png_bytes))
    output.load()

    if options.bgcolor:
        output = image_utils.composite_on_color(output, options.bgcolor)
    elif options.output_format == "jpeg":
        background = Image.new("RGB", output.size, (255, 255, 255))
        background.paste(output, mask=output.getchannel("A"))
        output = background

    fmt = options.output_format
    encoded = image_utils.encode(output, fmt, quality=options.quality)
    duration_ms = int((time.perf_counter() - started) * 1000)

    return ProcessResult(
        data=encoded,
        content_type=CONTENT_TYPES.get(fmt, "image/png"),
        input_info=info,
        duration_ms=duration_ms,
        output_format=fmt,
    )


def remove_color_background(
    raw: bytes,
    color: str,
    *,
    tolerance: int = 20,
    softness: int = 10,
    options: Optional[ProcessOptions] = None,
    settings: Optional[Settings] = None,
) -> ProcessResult:
    """Remove a solid background colour (chroma key style)."""
    settings = settings or get_settings()
    options = options or ProcessOptions()
    started = time.perf_counter()

    image, info = _load_and_validate(raw, settings)

    result = image_utils.remove_color(
        image, color, tolerance=tolerance, softness=softness
    )

    fmt = options.output_format
    if fmt == "jpeg":
        background = Image.new("RGB", result.size, (255, 255, 255))
        background.paste(result, mask=result.getchannel("A"))
        encoded_source = background
    else:
        encoded_source = result

    encoded = image_utils.encode(encoded_source, fmt, quality=options.quality)
    duration_ms = int((time.perf_counter() - started) * 1000)

    return ProcessResult(
        data=encoded,
        content_type=CONTENT_TYPES.get(fmt, "image/png"),
        input_info=info,
        duration_ms=duration_ms,
        output_format=fmt,
    )


__all__ = [
    "ProcessResult",
    "ImageValidationError",
    "EngineError",
    "EngineUnavailable",
    "remove_background",
    "remove_color_background",
]
