"""End-to-end tests for UrBG Remover."""

from __future__ import annotations

import base64
import io

from PIL import Image


# ---------------------------------------------------------------------------
# Health & status
# ---------------------------------------------------------------------------
def test_health_is_public(client):
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] in {"ok", "degraded"}
    assert "engine" in payload


def test_status_requires_api_key(client):
    response = client.get("/api/v1/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_api_key"


def test_status_with_api_key(client, api_key):
    response = client.get("/api/v1/status", headers={"X-API-Key": api_key})
    assert response.status_code == 200
    payload = response.json()
    assert payload["engine"]["model"]
    assert payload["limits"]["max_upload_mb"] >= 1


def test_bearer_token_is_accepted(client, api_key):
    response = client.get("/api/v1/status", headers={"Authorization": f"Bearer {api_key}"})
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Admin authentication
# ---------------------------------------------------------------------------
def test_dashboard_requires_authentication(client):
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.headers["location"]


def test_admin_api_requires_authentication(client):
    response = client.get("/admin/api/overview")
    assert response.status_code == 401


def test_login_rejects_wrong_password(client):
    response = client.post(
        "/admin/api/login", json={"username": "Arafat", "password": "not-the-password"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_login_with_correct_password(client):
    response = client.post(
        "/admin/api/login", json={"username": "Arafat", "password": "ARAFAT168642"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "Arafat"
    assert body["csrf_token"]


def test_session_cookie_is_http_only(client):
    response = client.post(
        "/admin/api/login", json={"username": "Arafat", "password": "ARAFAT168642"}
    )
    cookie = response.headers.get("set-cookie", "").lower()
    assert "urbg_session=" in cookie
    assert "httponly" in cookie
    assert "samesite=lax" in cookie


def test_logout_clears_the_session(client, admin_session):
    response = client.post("/admin/api/logout", headers={"X-CSRF-Token": admin_session})
    assert response.status_code == 200
    assert client.get("/admin/api/overview").status_code == 401


def test_repeated_failed_logins_are_locked_out(client):
    for _ in range(5):
        client.post("/admin/api/login", json={"username": "Arafat", "password": "nope"})

    response = client.post(
        "/admin/api/login", json={"username": "Arafat", "password": "ARAFAT168642"}
    )
    assert response.status_code == 429
    assert response.json()["error"]["code"] == "too_many_attempts"


def test_csrf_token_is_required_for_mutations(client, admin_session):
    response = client.post("/admin/api/keys", json={"name": "no-csrf"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "invalid_csrf_token"


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------
def test_api_key_is_only_shown_once(client, admin_session):
    response = client.post(
        "/admin/api/keys", json={"name": "one-time"}, headers={"X-CSRF-Token": admin_session}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["key"].startswith("urbg_")
    assert "never be shown again" in body["warning"]

    listing = client.get("/admin/api/keys").json()["keys"]
    stored = [k for k in listing if k["id"] == body["id"]][0]
    assert body["key"] not in str(stored)
    assert "key_hash" not in stored


def test_api_key_can_be_revoked(client, admin_session, api_key):
    created = client.post(
        "/admin/api/keys", json={"name": "revoke-me"}, headers={"X-CSRF-Token": admin_session}
    ).json()

    assert client.get("/api/v1/status", headers={"X-API-Key": created["key"]}).status_code == 200

    revoke = client.post(
        f"/admin/api/keys/{created['id']}/revoke", headers={"X-CSRF-Token": admin_session}
    )
    assert revoke.status_code == 200

    response = client.get("/api/v1/status", headers={"X-API-Key": created["key"]})
    assert response.status_code == 401
    assert response.json()["error"]["code"] in {"invalid_api_key", "revoked_api_key"}


def test_api_key_usage_is_tracked(client, api_key):
    client.get("/api/v1/status", headers={"X-API-Key": api_key})
    usage = client.get("/api/v1/usage", headers={"X-API-Key": api_key}).json()
    assert usage["totals"]["requests"] >= 1
    assert usage["key"]["id"] > 0


# ---------------------------------------------------------------------------
# Image processing
# ---------------------------------------------------------------------------
def test_remove_with_multipart_upload(client, api_key, sample_image, engine_ready):
    response = client.post(
        "/api/v1/remove",
        headers={"X-API-Key": api_key},
        files={"file": ("photo.jpg", sample_image, "image/jpeg")},
    )
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/png"
    assert response.content[:4] == b"\x89PNG"

    image = Image.open(io.BytesIO(response.content))
    assert image.mode == "RGBA"
    assert image.size == (320, 240)


def test_remove_with_raw_body(client, api_key, sample_image, engine_ready):
    response = client.post(
        "/api/v1/remove",
        headers={"X-API-Key": api_key, "Content-Type": "image/jpeg"},
        content=sample_image,
    )
    assert response.status_code == 200
    assert response.content[:4] == b"\x89PNG"


def test_remove_with_base64(client, api_key, sample_image, engine_ready):
    payload = {"image": base64.b64encode(sample_image).decode("ascii")}
    response = client.post(
        "/api/v1/remove/base64", json=payload, headers={"X-API-Key": api_key}
    )
    assert response.status_code == 200
    assert response.content[:4] == b"\x89PNG"


def test_remove_with_base64_data_url(client, api_key, sample_image, engine_ready):
    payload = {
        "image": "data:image/jpeg;base64," + base64.b64encode(sample_image).decode("ascii")
    }
    response = client.post(
        "/api/v1/remove/base64", json=payload, headers={"X-API-Key": api_key}
    )
    assert response.status_code == 200


def test_remove_json_response_format(client, api_key, sample_image, engine_ready):
    response = client.post(
        "/api/v1/remove?response_format=json",
        headers={"X-API-Key": api_key},
        files={"file": ("photo.jpg", sample_image, "image/jpeg")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    decoded = base64.b64decode(payload["data"]["base64"])
    assert decoded[:4] == b"\x89PNG"


def test_remove_rejects_unsupported_format(client, api_key):
    response = client.post(
        "/api/v1/remove",
        headers={"X-API-Key": api_key},
        files={"file": ("notes.txt", b"this is not an image", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] in {"unsupported_format", "invalid_image"}


def test_remove_rejects_empty_upload(client, api_key):
    response = client.post(
        "/api/v1/remove",
        headers={"X-API-Key": api_key},
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert response.status_code == 400


def test_remove_color_removes_the_background(client, api_key, sample_image):
    payload = {
        "image": base64.b64encode(sample_image).decode("ascii"),
        "color": "#3c78c8",
        "tolerance": 25,
        "softness": 10,
    }
    response = client.post("/api/v1/remove/color", json=payload, headers={"X-API-Key": api_key})
    assert response.status_code == 200, response.text
    image = Image.open(io.BytesIO(response.content))
    assert image.mode == "RGBA"
    alpha = image.getchannel("A")
    # The corners match the background colour and must be transparent.
    assert alpha.getpixel((2, 2)) < 40


def test_dashboard_removal_uses_the_session(client, admin_session, sample_image, engine_ready):
    response = client.post(
        "/admin/api/remove",
        headers={"X-CSRF-Token": admin_session},
        files={"file": ("photo.jpg", sample_image, "image/jpeg")},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["success"] is True
    assert base64.b64decode(payload["image"])[:4] == b"\x89PNG"


def test_dashboard_removal_requires_authentication(client, sample_image):
    response = client.post(
        "/admin/api/remove", files={"file": ("photo.jpg", sample_image, "image/jpeg")}
    )
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Dashboard data
# ---------------------------------------------------------------------------
def test_overview_returns_real_statistics(client, admin_session):
    response = client.get("/admin/api/overview")
    assert response.status_code == 200
    stats = response.json()["stats"]
    assert stats["total_requests"] >= 0
    assert stats["active_keys"] >= 1


def test_usage_endpoint_returns_a_daily_series(client, admin_session):
    response = client.get("/admin/api/usage?days=7")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["daily"]) == 7


def test_documentation_endpoints(client, admin_session):
    docs = client.get("/admin/api/docs").json()
    paths = [endpoint["path"] for endpoint in docs["endpoints"]]
    assert "/api/v1/remove" in paths
    assert "/api/v1/remove/url" in paths
    assert "/api/v1/remove/base64" in paths
    assert "/api/v1/remove/color" in paths
    assert "/api/v1/usage" in paths

    integrations = client.get("/admin/api/integrations").json()["integrations"]
    titles = [item["title"] for item in integrations]
    for expected in ["PHP (cURL)", "React (TypeScript)", "Flutter (Dart HTTP)", "Python (Requests)"]:
        assert expected in titles
    assert any("JavaScript" in title for title in titles)


def test_settings_can_be_updated(client, admin_session):
    response = client.put(
        "/admin/api/settings",
        json={"max_upload_mb": 8, "default_output_format": "webp"},
        headers={"X-CSRF-Token": admin_session},
    )
    assert response.status_code == 200
    assert response.json()["runtime"]["max_upload_mb"] == 8
    # restore the default for the remaining tests
    client.put(
        "/admin/api/settings",
        json={"max_upload_mb": 5, "default_output_format": "png"},
        headers={"X-CSRF-Token": admin_session},
    )


def test_openapi_schema_is_available(client):
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    assert "/api/v1/remove" in response.json()["paths"]
