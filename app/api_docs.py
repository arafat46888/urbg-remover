"""Machine readable API reference rendered in the dashboard."""

from __future__ import annotations

from typing import Any


def build_api_reference(base_url: str, max_upload_mb: int = 5) -> list[dict[str, Any]]:
    """Return the full endpoint reference for the API documentation page."""
    base = base_url.rstrip("/")
    return [
        {
            "method": "GET",
            "path": "/health",
            "auth": "None",
            "summary": "Service and AI engine health check.",
            "description": (
                "Public endpoint used by Railway (and any uptime monitor) to verify "
                "that the service is running and that the ONNX model is loaded."
            ),
            "query": [],
            "body": None,
            "response": "application/json",
            "example": f"curl {base}/health",
        },
        {
            "method": "GET",
            "path": "/api/v1/status",
            "auth": "X-API-Key",
            "summary": "API + AI engine status.",
            "description": "Returns service metadata, the active model and engine readiness.",
            "query": [],
            "body": None,
            "response": "application/json",
            "example": (
                f"curl {base}/api/v1/status \\\n  -H \"X-API-Key: YOUR_API_KEY\""
            ),
        },
        {
            "method": "POST",
            "path": "/api/v1/remove",
            "auth": "X-API-Key",
            "summary": "Remove the background of an uploaded image.",
            "description": (
                "Accepts a multipart/form-data upload (field name `file` or `image`) "
                "or a raw image body. Returns a transparent PNG by default. "
                f"Maximum upload size: {max_upload_mb} MB (configurable)."
            ),
            "query": [
                {
                    "name": "format",
                    "type": "string",
                    "default": "png",
                    "description": "Output format: png, webp or jpeg.",
                },
                {
                    "name": "response_format",
                    "type": "string",
                    "default": "binary",
                    "description": "binary (image bytes) or json (base64 payload).",
                },
                {
                    "name": "alpha_matting",
                    "type": "boolean",
                    "default": "false",
                    "description": "Enable alpha matting for softer edges.",
                },
                {
                    "name": "post_process_mask",
                    "type": "boolean",
                    "default": "false",
                    "description": "Refine the mask using a guided filter.",
                },
                {
                    "name": "only_mask",
                    "type": "boolean",
                    "default": "false",
                    "description": "Return only the alpha mask.",
                },
                {
                    "name": "bgcolor",
                    "type": "string",
                    "default": "null",
                    "description": "Flatten the result onto a hex colour, e.g. #ffffff.",
                },
            ],
            "body": "multipart/form-data (file) or raw image bytes",
            "response": "image/png (transparent)",
            "example": (
                f"curl -X POST {base}/api/v1/remove \\\n"
                "  -H \"X-API-Key: YOUR_API_KEY\" \\\n"
                "  -F \"file=@photo.jpg\" \\\n"
                "  --output result.png"
            ),
        },
        {
            "method": "POST",
            "path": "/api/v1/remove/url",
            "auth": "X-API-Key",
            "summary": "Remove the background of a remote image.",
            "description": (
                "Downloads a public image (http/https only; private network addresses "
                "are blocked) and returns the processed image."
            ),
            "query": [],
            "body": {
                "url": "string (required)",
                "format": "string (png|webp|jpeg, default png)",
                "response_format": "string (binary|json, default binary)",
                "alpha_matting": "boolean (default false)",
                "post_process_mask": "boolean (default false)",
                "only_mask": "boolean (default false)",
                "bgcolor": "string (hex colour, optional)",
            },
            "response": "image/png (transparent)",
            "example": (
                f"curl -X POST {base}/api/v1/remove/url \\\n"
                "  -H \"X-API-Key: YOUR_API_KEY\" \\\n"
                "  -H \"Content-Type: application/json\" \\\n"
                "  -d '{\"url\": \"https://example.com/photo.jpg\"}' \\\n"
                "  --output result.png"
            ),
        },
        {
            "method": "POST",
            "path": "/api/v1/remove/base64",
            "auth": "X-API-Key",
            "summary": "Remove the background of a base64 encoded image.",
            "description": (
                "Accepts a raw base64 string or a full data URL "
                "(`data:image/png;base64,...`)."
            ),
            "query": [],
            "body": {
                "image": "string (required, base64)",
                "format": "string (png|webp|jpeg, default png)",
                "response_format": "string (binary|json, default binary)",
                "alpha_matting": "boolean (default false)",
                "post_process_mask": "boolean (default false)",
                "only_mask": "boolean (default false)",
                "bgcolor": "string (hex colour, optional)",
            },
            "response": "image/png (transparent)",
            "example": (
                f"curl -X POST {base}/api/v1/remove/base64 \\\n"
                "  -H \"X-API-Key: YOUR_API_KEY\" \\\n"
                "  -H \"Content-Type: application/json\" \\\n"
                "  -d '{\"image\": \"$(base64 -w0 photo.jpg)\"}' \\\n"
                "  --output result.png"
            ),
        },
        {
            "method": "POST",
            "path": "/api/v1/remove/color",
            "auth": "X-API-Key",
            "summary": "Remove a solid background colour (chroma key).",
            "description": (
                "Removes every pixel matching the given colour and turns it "
                "transparent. Handy for product photos on a plain background."
            ),
            "query": [],
            "body": {
                "image": "string (base64, required unless url is given)",
                "url": "string (optional alternative to image)",
                "color": "string (hex colour, default #ffffff)",
                "tolerance": "integer 0-100 (default 20)",
                "softness": "integer 0-100 (default 10)",
                "format": "string (png|webp|jpeg, default png)",
                "response_format": "string (binary|json, default binary)",
            },
            "response": "image/png (transparent)",
            "example": (
                f"curl -X POST {base}/api/v1/remove/color \\\n"
                "  -H \"X-API-Key: YOUR_API_KEY\" \\\n"
                "  -H \"Content-Type: application/json\" \\\n"
                "  -d '{\"image\": \"$(base64 -w0 photo.jpg)\", \"color\": \"#ffffff\"}' \\\n"
                "  --output result.png"
            ),
        },
        {
            "method": "GET",
            "path": "/api/v1/usage",
            "auth": "X-API-Key",
            "summary": "Usage statistics for the calling API key.",
            "description": (
                "Returns request counters, bandwidth and a daily breakdown for the "
                "API key used to call the endpoint."
            ),
            "query": [
                {
                    "name": "days",
                    "type": "integer",
                    "default": "30",
                    "description": "Number of days of history to include (1-365).",
                }
            ],
            "body": None,
            "response": "application/json",
            "example": (
                f"curl {base}/api/v1/usage?days=30 \\\n  -H \"X-API-Key: YOUR_API_KEY\""
            ),
        },
    ]


ERROR_CODES: list[dict[str, str]] = [
    {"status": "400", "code": "invalid_image", "message": "The uploaded file is not a decodable image."},
    {"status": "400", "code": "unsupported_format", "message": "Only JPG, JPEG, PNG and WebP are accepted."},
    {"status": "401", "code": "missing_api_key", "message": "The X-API-Key header was not supplied."},
    {"status": "401", "code": "invalid_api_key", "message": "The API key is unknown or revoked."},
    {"status": "403", "code": "blocked_url", "message": "The URL points to a private or reserved address."},
    {"status": "413", "code": "file_too_large", "message": "The upload exceeds the configured size limit."},
    {"status": "422", "code": "validation_error", "message": "The request body failed validation."},
    {"status": "429", "code": "rate_limited", "message": "Too many requests - retry later."},
    {"status": "503", "code": "engine_unavailable", "message": "The AI model could not be loaded."},
]
