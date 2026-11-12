"""AI background removal engine (rembg + ONNX Runtime on CPU).

The engine keeps a single ONNX session alive for the lifetime of the process.
Images are handled entirely in memory: nothing is written to disk.
"""

from __future__ import annotations

import io
import os
import threading
import time
from typing import Any, Optional

from ..config import Settings, get_settings
from .image_utils import parse_hex_color


class EngineError(RuntimeError):
    """Raised when the AI engine cannot process an image."""


class EngineUnavailable(EngineError):
    """Raised when the model cannot be loaded at all."""


class AIEngine:
    """Thread-safe wrapper around :func:`rembg.remove`."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self._settings = settings or get_settings()
        self._lock = threading.Lock()
        self._session: Any = None
        self._model_name: str = self._settings.rembg_model
        self._error: Optional[str] = None
        self._load_ms: Optional[int] = None
        self._loaded_at: Optional[str] = None
        self._requests: int = 0

    # -- properties ---------------------------------------------------------
    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def is_ready(self) -> bool:
        return self._session is not None

    def set_model(self, model_name: str) -> None:
        """Change the active model (the session is rebuilt lazily)."""
        with self._lock:
            if model_name and model_name != self._model_name:
                self._model_name = model_name
                self._session = None
                self._error = None
                self._load_ms = None
                self._loaded_at = None

    # -- session management -------------------------------------------------
    def _ensure_session(self) -> Any:
        if self._session is not None:
            return self._session

        with self._lock:
            if self._session is not None:
                return self._session

            model_dir = str(self._settings.model_dir)
            os.makedirs(model_dir, exist_ok=True)
            # rembg / pooch download models into U2NET_HOME.
            os.environ.setdefault("U2NET_HOME", model_dir)
            os.environ["U2NET_HOME"] = model_dir

            started = time.monotonic()
            try:
                from rembg import new_session  # type: ignore

                session = new_session(
                    self._model_name,
                    providers=[self._settings.rembg_provider],
                )
            except Exception as exc:  # pragma: no cover - depends on environment
                self._error = f"{type(exc).__name__}: {exc}"
                raise EngineUnavailable(
                    f"AI model '{self._model_name}' could not be loaded: {self._error}"
                ) from exc

            self._session = session
            self._error = None
            self._load_ms = int((time.monotonic() - started) * 1000)
            self._loaded_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            return self._session

    def warmup(self) -> dict[str, Any]:
        """Pre-load the model (used at start-up and by the dashboard)."""
        try:
            self._ensure_session()
        except EngineUnavailable as exc:
            return {"ready": False, "error": str(exc)}
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "model": self._model_name,
            "provider": self._settings.rembg_provider,
            "ready": self.is_ready,
            "error": self._error,
            "load_ms": self._load_ms,
            "loaded_at": self._loaded_at,
            "processed": self._requests,
            "model_dir": str(self._settings.model_dir),
        }

    # -- inference ----------------------------------------------------------
    def remove(
        self,
        image_bytes: bytes,
        *,
        alpha_matting: bool = False,
        alpha_matting_foreground_threshold: int = 240,
        alpha_matting_background_threshold: int = 10,
        alpha_matting_erode_size: int = 10,
        post_process_mask: bool = False,
        only_mask: bool = False,
        bgcolor: Optional[str] = None,
    ) -> bytes:
        """Remove the background and return PNG bytes with an alpha channel."""
        from PIL import Image

        try:
            session = self._ensure_session()
        except EngineUnavailable:
            raise
        except Exception as exc:  # pragma: no cover
            raise EngineError(f"AI engine error: {exc}") from exc

        try:
            source = Image.open(io.BytesIO(image_bytes))
            source.load()
        except Exception as exc:
            raise EngineError(f"Unable to decode image: {exc}") from exc

        try:
            from rembg import remove as rembg_remove  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise EngineUnavailable(f"rembg is not available: {exc}") from exc

        kwargs: dict[str, Any] = {
            "session": session,
            "alpha_matting": alpha_matting,
            "alpha_matting_foreground_threshold": alpha_matting_foreground_threshold,
            "alpha_matting_background_threshold": alpha_matting_background_threshold,
            "alpha_matting_erode_size": alpha_matting_erode_size,
            "post_process_mask": post_process_mask,
            "only_mask": only_mask,
        }
        if bgcolor:
            # rembg expects an (R, G, B, A) tuple.
            red, green, blue = parse_hex_color(bgcolor)
            kwargs["bgcolor"] = (red, green, blue, 255)

        try:
            result = rembg_remove(source, **kwargs)
        except TypeError:
            # Older/newer rembg signatures: retry with the minimal call.
            result = rembg_remove(source, session=session)
        except Exception as exc:
            raise EngineError(f"Background removal failed: {exc}") from exc

        if isinstance(result, bytes):
            output = Image.open(io.BytesIO(result))
            output.load()
        else:
            output = result

        if only_mask:
            output = output.convert("L")
        elif output.mode not in ("RGBA", "LA"):
            output = output.convert("RGBA")

        buffer = io.BytesIO()
        output.save(buffer, format="PNG", optimize=True)
        self._requests += 1
        return buffer.getvalue()


_engine: Optional[AIEngine] = None
_engine_lock = threading.Lock()


def get_engine() -> AIEngine:
    """Return the process-wide AI engine."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = AIEngine(get_settings())
    return _engine


def reset_engine() -> None:
    """Testing helper."""
    global _engine
    with _engine_lock:
        _engine = None
