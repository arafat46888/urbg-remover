"""Pytest configuration - sets up an isolated environment before the app loads."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

TEST_ROOT = Path(tempfile.gettempdir()) / "urbg-remover-tests"

# The environment must be configured *before* app.main is imported.
os.environ.setdefault("ADMIN_USERNAME", "Arafat")
os.environ.setdefault("ADMIN_PASSWORD", "ARAFAT168642")
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-urbg-remover-0123456789")
os.environ.setdefault("DATA_DIR", str(TEST_ROOT / "data"))
os.environ.setdefault("DB_PATH", str(TEST_ROOT / "data" / "urbg-test.db"))
os.environ.setdefault("MODEL_DIR", str(TEST_ROOT / "models"))
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("ENGINE_WARMUP_ON_START", "false")


@pytest.fixture(autouse=True)
def reset_throttle():
    """Keep the login rate limiter isolated between tests."""
    from app.dependencies import reset_login_throttle

    reset_login_throttle()
    yield
    reset_login_throttle()


@pytest.fixture()
def client():
    """A TestClient with an isolated cookie jar (fresh session per test)."""
    from fastapi.testclient import TestClient

    from app.database import init_db, reset_db
    from app.main import app

    reset_db()
    init_db()

    with TestClient(app) as test_client:
        yield test_client

    reset_db()


@pytest.fixture()
def admin_session(client):
    """Log in and return the CSRF token."""
    response = client.post(
        "/admin/api/login", json={"username": "Arafat", "password": "ARAFAT168642"}
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


@pytest.fixture()
def api_key(client, admin_session):
    """Create an API key and return the plaintext value."""
    response = client.post(
        "/admin/api/keys",
        json={"name": "pytest"},
        headers={"X-CSRF-Token": admin_session},
    )
    assert response.status_code == 200, response.text
    return response.json()["key"]


@pytest.fixture(scope="session")
def engine_ready():
    """Ensure the ONNX model is available; skip the test when it cannot load."""
    from app.services.ai_engine import get_engine

    status = get_engine().warmup()
    if not status.get("ready"):
        pytest.skip(f"AI engine unavailable: {status.get('error')}")
    return True


@pytest.fixture(scope="session")
def sample_image() -> bytes:
    """A small synthetic JPEG (red circle on a coloured background)."""
    import io

    from PIL import Image, ImageDraw

    image = Image.new("RGB", (320, 240), (40, 90, 180))
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, 320, 240], fill=(60, 120, 200))
    draw.ellipse([90, 50, 230, 200], fill=(225, 70, 60))
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()
