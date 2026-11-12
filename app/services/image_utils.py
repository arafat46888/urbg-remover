"""Image validation and manipulation helpers.

Everything here works on in-memory buffers - uploaded images are never written
to disk.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from typing import Any, Optional, Tuple

import numpy as np
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
MAX_PIXELS = 60_000_000  # guard against decompression bombs

_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


class ImageValidationError(ValueError):
    """Raised when an uploaded image is not acceptable."""

    def __init__(self, message: str, code: str = "invalid_image") -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ImageInfo:
    format: str
    width: int
    height: int
    mode: str
    size_bytes: int
    has_alpha: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "format": self.format,
            "width": self.width,
            "height": self.height,
            "mode": self.mode,
            "size_bytes": self.size_bytes,
            "has_alpha": self.has_alpha,
        }


def parse_hex_color(value: str) -> Tuple[int, int, int]:
    """Parse ``#rrggbb`` / ``rgb`` / ``rrggbb`` into an RGB tuple."""
    if not value:
        raise ImageValidationError("A colour value is required.", "invalid_color")
    match = _HEX_RE.match(value.strip())
    if not match:
        raise ImageValidationError(
            f"Invalid colour '{value}'. Use a hex value such as #ffffff.", "invalid_color"
        )
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return int(digits[0:2], 16), int(digits[2:4], 16), int(digits[4:6], 16)


def sniff_format(data: bytes) -> Optional[str]:
    """Detect the image format from magic bytes without decoding the image."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "GIF"
    if data[:2] == b"BM":
        return "BMP"
    return None


def load_image(data: bytes) -> Image.Image:
    """Decode bytes into a Pillow image (fully loaded, EXIF corrected)."""
    if not data:
        raise ImageValidationError("The uploaded file is empty.", "empty_file")
    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except UnidentifiedImageError as exc:
        raise ImageValidationError(
            "The uploaded file is not a valid image.", "invalid_image"
        ) from exc
    except Exception as exc:  # decompression errors, truncated files, ...
        raise ImageValidationError(f"The image could not be decoded: {exc}", "invalid_image") from exc

    try:
        image = ImageOps.exif_transpose(image)
    except Exception:
        pass
    return image


def validate_upload(
    data: bytes,
    *,
    max_bytes: int,
    max_dimension: int,
) -> Tuple[Image.Image, ImageInfo]:
    """Validate an uploaded image and return the decoded image plus metadata."""
    if not data:
        raise ImageValidationError("The uploaded file is empty.", "empty_file")
    if len(data) > max_bytes:
        raise ImageValidationError(
            f"File is larger than the {max_bytes // (1024 * 1024)} MB limit.", "file_too_large"
        )

    detected = sniff_format(data)
    if detected is None:
        raise ImageValidationError(
            "Unsupported file type. Use JPG, JPEG, PNG or WebP.", "unsupported_format"
        )
    if detected not in ALLOWED_FORMATS:
        raise ImageValidationError(
            f"Unsupported image format '{detected}'. Use JPG, JPEG, PNG or WebP.",
            "unsupported_format",
        )

    image = load_image(data)

    if image.format and image.format.upper() not in ALLOWED_FORMATS:
        raise ImageValidationError(
            f"Unsupported image format '{image.format}'. Use JPG, JPEG, PNG or WebP.",
            "unsupported_format",
        )

    width, height = image.size
    if width <= 0 or height <= 0:
        raise ImageValidationError("The image has invalid dimensions.", "invalid_dimensions")
    if width > max_dimension or height > max_dimension:
        raise ImageValidationError(
            f"Image dimensions {width}x{height} exceed the {max_dimension}px limit.",
            "invalid_dimensions",
        )
    if width * height > MAX_PIXELS:
        raise ImageValidationError("The image contains too many pixels.", "invalid_dimensions")

    info = ImageInfo(
        format=(image.format or detected).upper(),
        width=width,
        height=height,
        mode=image.mode,
        size_bytes=len(data),
        has_alpha="A" in image.getbands(),
    )
    return image, info


def to_png_bytes(image: Image.Image, optimize: bool = True) -> bytes:
    buffer = io.BytesIO()
    output = image
    if output.mode not in ("RGBA", "LA", "P"):
        output = output.convert("RGBA")
    elif output.mode == "P":
        output = output.convert("RGBA")
    output.save(buffer, format="PNG", optimize=optimize)
    return buffer.getvalue()


def encode(image: Image.Image, fmt: str, *, quality: int = 92) -> bytes:
    """Encode a Pillow image as PNG / WEBP / JPEG bytes."""
    fmt = (fmt or "png").lower()
    buffer = io.BytesIO()
    if fmt in {"jpg", "jpeg"}:
        flat = image.convert("RGB")
        flat.save(buffer, format="JPEG", quality=quality, optimize=True)
    elif fmt == "webp":
        output = image if image.mode in ("RGBA", "RGB") else image.convert("RGBA")
        output.save(buffer, format="WEBP", quality=quality, method=4)
    else:
        output = image if image.mode in ("RGBA", "LA", "P") else image.convert("RGBA")
        if output.mode == "P":
            output = output.convert("RGBA")
        output.save(buffer, format="PNG")
    return buffer.getvalue()


def _rgb_to_hsv(arr: np.ndarray) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Vectorised RGB (0..1) -> HSV conversion. Returns (h in 0..1, s, v)."""
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    maxc = np.max(arr, axis=-1)
    minc = np.min(arr, axis=-1)
    diff = maxc - minc

    v = maxc
    with np.errstate(divide="ignore", invalid="ignore"):
        s = np.where(maxc > 0, diff / np.where(maxc == 0, 1.0, maxc), 0.0)

        rc = (maxc - r) / np.where(diff == 0, 1.0, diff)
        gc = (maxc - g) / np.where(diff == 0, 1.0, diff)
        bc = (maxc - b) / np.where(diff == 0, 1.0, diff)

        h = np.select(
            [diff == 0, maxc == r, maxc == g],
            [0.0, bc - gc, 2.0 + rc - bc],
            default=0.0,
        )
        h = (h / 6.0) % 1.0
    return h, s, v


def remove_color(
    image: Image.Image,
    color: str,
    *,
    tolerance: int = 20,
    softness: int = 10,
) -> Image.Image:
    """Chroma-key style removal of a solid background colour.

    ``tolerance`` (0-100) controls how far a pixel may deviate from the target
    colour and still be treated as background.  ``softness`` (0-100) feathers
    the edge between background and foreground.
    """
    target = parse_hex_color(color)
    tolerance = max(0, min(100, int(tolerance)))
    softness = max(0, min(100, int(softness)))

    rgba = image.convert("RGBA")
    rgb = np.asarray(rgba.convert("RGB"), dtype=np.float32) / 255.0
    height, width = rgb.shape[:2]

    target_arr = np.asarray(target, dtype=np.float32) / 255.0
    h, s, v = _rgb_to_hsv(rgb)
    th, ts, tv = _rgb_to_hsv(target_arr.reshape(1, 1, 3))
    th = float(th[0, 0])
    ts = float(ts[0, 0])
    tv = float(tv[0, 0])

    value_window = max(0.02, tolerance / 100.0)
    value_dist = np.abs(v - tv)

    if ts <= 0.18:
        # Achromatic target (white / black / grey): match on brightness.
        distance = value_dist / value_window
    else:
        hue_dist = np.abs(h - th)
        hue_dist = np.minimum(hue_dist, 1.0 - hue_dist)  # circular distance
        hue_window = max(0.02, tolerance / 100.0 * 0.35)
        hue_score = hue_dist / hue_window
        value_score = value_dist / value_window
        saturation_ok = s >= max(0.05, ts * 0.35)
        distance = np.where(saturation_ok, np.maximum(hue_score, value_score), value_score)

    if softness > 0:
        feather = max(0.05, softness / 100.0)
        alpha = np.clip((distance - 1.0) / feather, 0.0, 1.0)
    else:
        alpha = np.clip(distance - 1.0, 0.0, 1.0)

    alpha_u8 = (alpha * 255.0).astype(np.uint8)
    existing = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
    combined = ((existing.astype(np.float32) * alpha_u8.astype(np.float32)) / 255.0).astype(np.uint8)

    out = np.dstack([np.asarray(rgba.convert("RGB"), dtype=np.uint8), combined])
    return Image.fromarray(out, mode="RGBA").resize((width, height), Image.LANCZOS)


def composite_on_color(image: Image.Image, color: str) -> Image.Image:
    """Flatten a transparent image onto a solid background colour."""
    bg = parse_hex_color(color)
    canvas = Image.new("RGB", image.size, bg)
    rgba = image.convert("RGBA")
    canvas.paste(rgba, mask=rgba.getchannel("A"))
    return canvas


def image_to_data_url(image: Image.Image) -> str:
    """Return a base64 data URL for the given image (PNG)."""
    import base64

    payload = base64.b64encode(to_png_bytes(image)).decode("ascii")
    return f"data:image/png;base64,{payload}"


def decode_data_url(payload: str) -> bytes:
    """Decode a base64 (optionally data-URL wrapped) payload into raw bytes."""
    import base64

    value = payload.strip()
    if value.startswith("data:"):
        _, _, value = value.partition(",")
    value = re.sub(r"\s+", "", value)
    if not value:
        raise ImageValidationError("The base64 payload is empty.", "empty_file")
    try:
        decoded = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise ImageValidationError(
            "The base64 payload could not be decoded.", "invalid_base64"
        ) from exc
    if not decoded:
        raise ImageValidationError("The base64 payload is empty.", "empty_file")
    return decoded
