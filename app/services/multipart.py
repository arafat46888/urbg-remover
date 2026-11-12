"""In-memory multipart/form-data parser.

Starlette's default parser spools uploads larger than 1 MB to a temporary
file on disk.  UrBG Remover keeps every upload in memory instead, so the
parser below reads the (size limited) request body and stores the file parts
as ``bytes``.
"""

from __future__ import annotations

import re
from typing import Any, Optional

try:  # python-multipart >= 0.0.12 exposes the parser through this module
    from python_multipart.multipart import MultipartParser
except ImportError:  # pragma: no cover - very old versions
    from multipart.multipart import MultipartParser  # type: ignore

_NAME_RE = re.compile(rb'name="([^"]*)"')
_FILENAME_RE = re.compile(rb'filename="([^"]*)"')
_FILENAME_STAR_RE = re.compile(rb"filename\*=UTF-8''([^;\r\n]*)", re.IGNORECASE)


class MultipartError(ValueError):
    """Raised when a multipart body cannot be parsed."""


class _Collector:
    """Callback target for :class:`MultipartParser`."""

    def __init__(self, max_bytes: int) -> None:
        self.fields: dict[str, str] = {}
        self.files: dict[str, bytes] = {}
        self.max_bytes = max_bytes
        self._part_name: Optional[str] = None
        self._part_filename: Optional[str] = None
        self._header_field = bytearray()
        self._header_value = bytearray()
        self._data = bytearray()
        self._total = 0

    # -- callbacks ----------------------------------------------------------
    def on_part_begin(self) -> None:
        self._part_name = None
        self._part_filename = None
        self._data = bytearray()

    def on_header_begin(self) -> None:
        self._header_field = bytearray()
        self._header_value = bytearray()

    def on_header_field(self, data: bytes, start: int, end: int) -> None:
        self._header_field += data[start:end]

    def on_header_value(self, data: bytes, start: int, end: int) -> None:
        self._header_value += data[start:end]

    def on_header_end(self) -> None:
        field = bytes(self._header_field).strip().lower()
        value = bytes(self._header_value)
        if field == b"content-disposition":
            match = _NAME_RE.search(value)
            if match:
                self._part_name = match.group(1).decode("utf-8", "replace")
            filename_match = _FILENAME_RE.search(value)
            if filename_match:
                self._part_filename = filename_match.group(1).decode("utf-8", "replace")
            else:
                star = _FILENAME_STAR_RE.search(value)
                if star:
                    self._part_filename = star.group(1).decode("utf-8", "replace")
        self._header_field = bytearray()
        self._header_value = bytearray()

    def on_headers_finished(self) -> None:
        self._header_field = bytearray()
        self._header_value = bytearray()

    def on_part_data(self, data: bytes, start: int, end: int) -> None:
        chunk = data[start:end]
        self._total += len(chunk)
        if self._total > self.max_bytes:
            raise MultipartError("The upload exceeds the maximum allowed size.")
        self._data += chunk

    def on_part_end(self) -> None:
        name = self._part_name or ""
        if self._part_filename is not None:
            self.files[name] = bytes(self._data)
        elif name:
            self.fields[name] = bytes(self._data).decode("utf-8", "replace")
        self._data = bytearray()

    def on_end(self) -> None:
        return None


def parse_content_type(value: str) -> tuple[str, dict[str, str]]:
    """Parse a Content-Type header into ``(media_type, parameters)``."""
    if not value:
        return "", {}
    parts = value.split(";")
    media_type = parts[0].strip().lower()
    params: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            continue
        key, _, raw = part.partition("=")
        raw = raw.strip()
        if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
            raw = raw[1:-1]
        params[key.strip().lower()] = raw
    return media_type, params


def parse_multipart(
    body: bytes,
    content_type: str,
    *,
    max_bytes: int,
) -> tuple[dict[str, str], dict[str, bytes]]:
    """Parse a multipart/form-data body.

    Returns ``(fields, files)`` where ``files`` maps the field name to the
    raw bytes of that part.
    """
    media_type, params = parse_content_type(content_type)
    if media_type != "multipart/form-data":
        raise MultipartError("Expected a multipart/form-data body.")
    boundary = params.get("boundary")
    if not boundary:
        raise MultipartError("The multipart boundary is missing.")

    collector = _Collector(max_bytes)
    callbacks = {
        "on_part_begin": collector.on_part_begin,
        "on_part_data": collector.on_part_data,
        "on_part_end": collector.on_part_end,
        "on_header_begin": collector.on_header_begin,
        "on_header_field": collector.on_header_field,
        "on_header_value": collector.on_header_value,
        "on_header_end": collector.on_header_end,
        "on_headers_finished": collector.on_headers_finished,
        "on_end": collector.on_end,
    }
    parser = MultipartParser(boundary, callbacks)  # type: ignore[arg-type]
    try:
        parser.write(body)
        parser.finalize()
    except MultipartError:
        raise
    except Exception as exc:  # pragma: no cover - malformed payloads
        raise MultipartError(f"The multipart body could not be parsed: {exc}") from exc

    return collector.fields, collector.files


def pick_file(files: dict[str, bytes], *names: str) -> Optional[bytes]:
    """Return the first available file part from the given field names."""
    for name in names:
        if name in files and files[name]:
            return files[name]
    for value in files.values():
        if value:
            return value
    return None


__all__ = ["MultipartError", "parse_multipart", "pick_file"]


def _unused(*_args: Any) -> None:  # pragma: no cover - keeps linters quiet
    return None
