"""Copy-ready integration snippets rendered in the dashboard.

The snippets never contain a real secret - the API key is always read from an
environment variable / server side configuration.
"""

from __future__ import annotations

from typing import Any

PLACEHOLDER = "{{BASE_URL}}"


def _render(template: str, base_url: str) -> str:
    return template.replace(PLACEHOLDER, base_url.rstrip("/"))


PHP_SNIPPET = r'''<?php
/**
 * UrBG Remover - PHP (cURL) integration.
 * The API key lives on the server only - never ship it to the browser.
 */

$apiKey   = getenv('URBG_API_KEY');               // e.g. urbg_xxx
$endpoint = '{{BASE_URL}}/api/v1/remove';
$filePath = '/path/to/photo.jpg';

if ($apiKey === false || $apiKey === '') {
    http_response_code(500);
    exit('URBG_API_KEY is not configured');
}

$curl = curl_init($endpoint);
curl_setopt_array($curl, [
    CURLOPT_POST           => true,
    CURLOPT_RETURNTRANSFER => true,
    CURLOPT_TIMEOUT        => 60,
    CURLOPT_HTTPHEADER     => [
        'X-API-Key: ' . $apiKey,
        'Accept: image/png',
    ],
    CURLOPT_POSTFIELDS     => [
        'file' => new CURLFile($filePath, 'image/jpeg', basename($filePath)),
    ],
]);

$png   = curl_exec($curl);
$error = curl_error($curl);
$status = (int) curl_getinfo($curl, CURLINFO_HTTP_CODE);
curl_close($curl);

// --- Error handling -------------------------------------------------------
if ($status !== 200) {
    $payload = json_decode((string) $png, true);
    $message = $payload['error']['message'] ?? 'Background removal failed';
    $code    = $payload['error']['code'] ?? 'unknown_error';
    error_log("UrBG error [{$code}]: {$message}");
    http_response_code($status === 0 ? 502 : $status);
    exit($message);
}

// --- Response handling ----------------------------------------------------
file_put_contents('/path/to/result.png', $png);
echo 'Saved transparent PNG (' . strlen($png) . " bytes)\n";
'''

JS_SNIPPET = r'''/**
 * UrBG Remover - Browser (Fetch API) integration.
 *
 * IMPORTANT: never hard-code your API key in public JavaScript. Call your own
 * backend endpoint (see the proxy example below) and let the server talk to
 * UrBG Remover with the secret key.
 */

// --- Recommended: call your own backend proxy -----------------------------
async function removeBackground(file) {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch('/api/urbg/remove', {
    method: 'POST',
    body: formData,            // do NOT set Content-Type manually
  });

  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = await response.json();
      message = payload.error?.message ?? payload.message ?? message;
    } catch (_) { /* non JSON error body */ }
    throw new Error(message);
  }

  const blob = await response.blob();
  return URL.createObjectURL(blob);   // preview URL
}

// --- Direct call (only for PRIVATE, non-public apps) ----------------------
// async function removeBackgroundDirect(file) {
//   const formData = new FormData();
//   formData.append('file', file);
//   const response = await fetch('{{BASE_URL}}/api/v1/remove', {
//     method: 'POST',
//     headers: { 'X-API-Key': 'YOUR_API_KEY' },
//     body: formData,
//   });
//   if (!response.ok) {
//     const payload = await response.json();
//     throw new Error(payload.error?.message ?? 'Removal failed');
//   }
//   return URL.createObjectURL(await response.blob());
// }
'''

REACT_SNIPPET = r'''// UrBG Remover - React + TypeScript integration
// The API key stays on your server; the browser only talks to your own API.

export type RemovalResult = {
  imageUrl: string;
  filename: string;
  durationMs: number;
};

async function removeBackground(file: File): Promise<RemovalResult> {
  const formData = new FormData();
  formData.append('file', file);

  const response = await fetch('/api/urbg/remove', {
    method: 'POST',
    body: formData,
  });

  if (!response.ok) {
    let message = `Removal failed (${response.status})`;
    try {
      const payload = await response.json();
      message = payload.error?.message ?? message;
    } catch {
      /* ignore JSON parse errors */
    }
    throw new Error(message);
  }

  const blob = await response.blob();
  return {
    imageUrl: URL.createObjectURL(blob),
    filename: file.name.replace(/\.[^.]+$/, '') + '-transparent.png',
    durationMs: Number(response.headers.get('X-Process-Time-Ms') ?? 0),
  };
}

// --- React component ------------------------------------------------------
export function BackgroundRemover() {
  const [preview, setPreview] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [busy, setBusy] = React.useState(false);

  const onSelect = async (file: File | undefined) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const result = await removeBackground(file);
      setPreview(result.imageUrl);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <input
        type="file"
        accept="image/png,image/jpeg,image/webp"
        onChange={(event) => onSelect(event.target.files?.[0])}
      />
      {busy && <p>Removing background…</p>}
      {error && <p role="alert">{error}</p>}
      {preview && <img src={preview} alt="Transparent result" />}
    </div>
  );
}
'''

FLUTTER_SNIPPET = r'''// UrBG Remover - Flutter (Dart) integration
// Point this at your own backend proxy so the API key never ships in the app.

import 'dart:bytes';
import 'dart:typed_data';
import 'package:http/http.dart' as http;

class UrbgException implements Exception {
  UrbgException(this.statusCode, this.code, this.message);
  final int statusCode;
  final String code;
  final String message;

  @override
  String toString() => 'UrbgException($statusCode/$code): $message';
}

Future<Uint8List> removeBackground({
  required Uint8List bytes,
  required String filename,
  String endpoint = '/api/urbg/remove',
}) async {
  final request = http.MultipartRequest('POST', Uri.parse(endpoint));
  request.files.add(
    http.MultipartFile.fromBytes('file', bytes, filename: filename),
  );

  final streamed = await request.send();
  final response = await http.Response.fromStream(streamed);

  if (response.statusCode != 200) {
    String code = 'unknown_error';
    String message = 'Background removal failed (${response.statusCode})';
    try {
      final payload = jsonDecode(response.body) as Map<String, dynamic>;
      final error = payload['error'] as Map<String, dynamic>;
      code = error['code']?.toString() ?? code;
      message = error['message']?.toString() ?? message;
    } catch (_) {
      /* non JSON error body */
    }
    throw UrbgException(response.statusCode, code, message);
  }

  return response.bodyBytes;
}
'''

PYTHON_SNIPPET = r'''"""UrBG Remover - Python (Requests) integration."""

import os
import requests

API_KEY = os.environ["URBG_API_KEY"]          # never hard-code the key
BASE_URL = "{{BASE_URL}}"


def remove_background(image_path: str, output_path: str = "result.png") -> dict:
    """Upload a local image and save the transparent PNG result."""
    with open(image_path, "rb") as handle:
        response = requests.post(
            f"{BASE_URL}/api/v1/remove",
            headers={
                "X-API-Key": API_KEY,
                "Accept": "image/png",
            },
            files={"file": (os.path.basename(image_path), handle, "image/jpeg")},
            timeout=60,
        )

    if response.status_code != 200:
        try:
            payload = response.json()
            code = payload.get("error", {}).get("code", "unknown_error")
            message = payload.get("error", {}).get("message", response.text)
        except ValueError:
            code, message = "unknown_error", response.text
        raise RuntimeError(f"UrBG error [{code}]: {message}")

    with open(output_path, "wb") as out:
        out.write(response.content)

    return {
        "path": output_path,
        "bytes": len(response.content),
        "duration_ms": int(response.headers.get("X-Process-Time-Ms", 0)),
    }


if __name__ == "__main__":
    print(remove_background("photo.jpg"))
'''

PROXY_SNIPPET = r'''// Secure backend proxy - recommended for web front-ends.
// The browser never sees the UrBG API key.

import express from 'express';
import multer from 'multer';

const app = express();
const upload = multer({ limits: { fileSize: 5 * 1024 * 1024 } });

const URBG_API_KEY = process.env.URBG_API_KEY;      // server side secret
const URBG_ENDPOINT = `${process.env.URBG_BASE_URL}/api/v1/remove`;

app.post('/api/urbg/remove', upload.single('file'), async (req, res) => {
  if (!req.file) {
    return res.status(400).json({ error: { message: 'No file uploaded' } });
  }

  try {
    const form = new FormData();
    form.append('file', new Blob([req.file.buffer]), req.file.originalname);

    const upstream = await fetch(URBG_ENDPOINT, {
      method: 'POST',
      headers: { 'X-API-Key': URBG_API_KEY },
      body: form,
    });

    if (!upstream.ok) {
      const payload = await upstream.json().catch(() => ({}));
      return res.status(upstream.status).json({
        error: { message: payload?.error?.message ?? 'Removal failed' },
      });
    }

    const buffer = Buffer.from(await upstream.arrayBuffer());
    res.setHeader('Content-Type', 'image/png');
    res.setHeader('X-Process-Time-Ms', upstream.headers.get('X-Process-Time-Ms') ?? '0');
    res.send(buffer);
  } catch (error) {
    res.status(502).json({ error: { message: 'Upstream request failed' } });
  }
});

app.listen(3000);
'''


def build_integrations(base_url: str) -> list[dict[str, Any]]:
    """Return the integration examples with the live base URL injected."""
    return [
        {
            "id": "php",
            "title": "PHP (cURL)",
            "language": "php",
            "filename": "remove-background.php",
            "endpoint": f"{base_url.rstrip('/')}/api/v1/remove",
            "auth_header": "X-API-Key: YOUR_API_KEY",
            "notes": [
                "Read the key from an environment variable - never hard-code it.",
                "CURLOPT_RETURNTRANSFER gives you the raw PNG bytes.",
                "Non-200 responses carry a JSON body with error.code and error.message.",
            ],
            "code": _render(PHP_SNIPPET, base_url),
        },
        {
            "id": "javascript",
            "title": "HTML + JavaScript (Fetch API)",
            "language": "javascript",
            "filename": "remove-background.js",
            "endpoint": f"{base_url.rstrip('/')}/api/v1/remove",
            "auth_header": "X-API-Key: YOUR_API_KEY",
            "notes": [
                "Never embed the API key in public JavaScript - use the proxy below.",
                "The direct-call version is only safe for private, authenticated apps.",
                "Use FormData so the browser sets the multipart boundary for you.",
            ],
            "code": _render(JS_SNIPPET, base_url),
        },
        {
            "id": "react",
            "title": "React (TypeScript)",
            "language": "typescript",
            "filename": "BackgroundRemover.tsx",
            "endpoint": f"{base_url.rstrip('/')}/api/v1/remove",
            "auth_header": "X-API-Key: YOUR_API_KEY",
            "notes": [
                "Call your own backend route so the key never reaches the browser.",
                "The component shows error handling and a busy state.",
                "Revoke the object URL when the component unmounts.",
            ],
            "code": _render(REACT_SNIPPET, base_url),
        },
        {
            "id": "flutter",
            "title": "Flutter (Dart HTTP)",
            "language": "dart",
            "filename": "urbg_client.dart",
            "endpoint": f"{base_url.rstrip('/')}/api/v1/remove",
            "auth_header": "X-API-Key: YOUR_API_KEY",
            "notes": [
                "Ship a backend proxy endpoint; do not embed the key in the app binary.",
                "MultipartRequest mirrors the multipart/form-data upload.",
                "Errors are surfaced through the UrbgException class.",
            ],
            "code": _render(FLUTTER_SNIPPET, base_url),
        },
        {
            "id": "python",
            "title": "Python (Requests)",
            "language": "python",
            "filename": "urbg_client.py",
            "endpoint": f"{base_url.rstrip('/')}/api/v1/remove",
            "auth_header": "X-API-Key: YOUR_API_KEY",
            "notes": [
                "Load the key from os.environ so it stays out of version control.",
                "The function returns the saved file path and processing time.",
                "Failures raise a RuntimeError containing the API error code.",
            ],
            "code": _render(PYTHON_SNIPPET, base_url),
        },
        {
            "id": "proxy",
            "title": "Secure Backend Proxy (Node.js)",
            "language": "javascript",
            "filename": "proxy.js",
            "endpoint": f"{base_url.rstrip('/')}/api/v1/remove",
            "auth_header": "X-API-Key: YOUR_API_KEY",
            "notes": [
                "This is the pattern to use for every public web front-end.",
                "The secret key stays on the server; the browser only sees your route.",
                "Add your own authentication/authorisation before exposing the route.",
            ],
            "code": _render(PROXY_SNIPPET, base_url),
        },
    ]
