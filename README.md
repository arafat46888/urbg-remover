# UrBG Remover

**Self-hosted AI background removal API with a private admin dashboard.**

UrBG Remover runs the real [`rembg`](https://github.com/danielgatis/rembg) ONNX model on
CPU, exposes a small, documented REST API, and ships with a dark admin console for
generating API keys, processing images and watching usage.

Everything runs in **one** Railway service — no external AI provider, no database
service, no paid dependencies.

---

## Table of contents

1. [Features](#features)
2. [Project structure](#project-structure)
3. [Requirements](#requirements)
4. [Local installation](#local-installation)
5. [Configuration](#configuration)
6. [Running locally](#running-locally)
7. [Local testing](#local-testing)
8. [Railway deployment](#railway-deployment)
9. [REST API reference](#rest-api-reference)
10. [Integration examples](#integration-examples)
11. [Security model](#security-model)
12. [Troubleshooting](#troubleshooting)

---

## Features

| Area | What it does |
| --- | --- |
| **AI engine** | `rembg` + ONNX Runtime (CPU). Default model `u2netp` (4.7 MB), switchable to `u2net`, `u2net_human_seg`, `silueta` or `isnet-general-use` from the dashboard. |
| **Public API** | `GET /health`, `GET /api/v1/status`, `POST /api/v1/remove`, `POST /api/v1/remove/url`, `POST /api/v1/remove/base64`, `POST /api/v1/remove/color`, `GET /api/v1/usage`. |
| **Admin dashboard** | Overview, Background Remover, API Keys, API Documentation, Integrations, Usage Statistics, Settings — responsive dark UI. |
| **API keys** | Generated with `secrets`, stored as a SHA-256 hash only, shown exactly once, revocable, with per-key request/image counters and last-used timestamps. |
| **Auth** | Signed, HTTP-only, `SameSite=Lax`, `Secure` session cookie + PBKDF2-HMAC-SHA256 password verification + CSRF tokens + login rate limiting / lockout. |
| **Storage** | SQLite (WAL mode) on the Railway volume. Uploads are processed entirely in memory and never written to disk. |
| **Documentation** | Live API reference and copy-ready PHP / JavaScript / React / Flutter / Python integration snippets rendered inside the dashboard. |

---

## Project structure

```
urbg-remover/
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI application factory, middleware, lifespan
│   ├── config.py               # Environment driven configuration
│   ├── database.py             # SQLite schema + helpers (WAL, thread safe)
│   ├── security.py             # Password hashing, API keys, rate limiters
│   ├── dependencies.py         # Auth dependencies (admin session, API key, CSRF)
│   ├── errors.py               # JSON error envelope + exception handlers
│   ├── middleware.py           # Usage accounting + security headers
│   ├── schemas.py              # Pydantic request models
│   ├── api_docs.py             # Machine readable API reference
│   ├── integrations.py         # Copy-ready integration snippets
│   ├── routers/
│   │   ├── public.py           # /health
│   │   ├── api.py              # /api/v1/*
│   │   ├── admin.py            # /admin/api/*
│   │   └── pages.py            # / and /login
│   ├── services/
│   │   ├── ai_engine.py        # rembg / ONNX session wrapper
│   │   ├── image_utils.py      # Validation, encoding, colour removal
│   │   ├── processor.py        # The removal pipeline
│   │   ├── keys.py             # API key CRUD + usage statistics
│   │   ├── fetcher.py          # Safe remote image download (SSRF guarded)
│   │   ├── multipart.py        # In-memory multipart parser
│   │   ├── runtime.py          # Dashboard-editable runtime settings
│   │   └── admin_auth.py       # Admin password sync / verification
│   └── static/
│       ├── index.html          # Dashboard
│       ├── login.html          # Login page
│       ├── css/styles.css      # Dark theme
│       └── js/{app.js,login.js}
├── tests/
│   ├── conftest.py
│   └── test_api.py             # 30 end-to-end tests
├── data/                       # SQLite database (created at runtime, git-ignored)
├── models/                     # ONNX model cache (created at runtime, git-ignored)
├── Dockerfile
├── docker-entrypoint.sh
├── railway.json
├── requirements.txt
├── .env.example
├── .dockerignore
├── .gitignore
└── README.md
```

---

## Requirements

* **Python 3.11** (3.10 – 3.12 work as well; the Docker image uses 3.11)
* ~450 MB of disk for the dependencies, ~5 MB for the default ONNX model
* No GPU — the engine uses `CPUExecutionProvider`
* No external services

---

## Local installation

### Windows (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

### Configure the environment

```powershell
Copy-Item .env.example .env      # Windows
# cp .env.example .env            # macOS / Linux
```

At minimum set:

```env
ADMIN_USERNAME=Arafat
ADMIN_PASSWORD=ARAFAT168642
SECRET_KEY=<a long random string>
```

Generate a secret key with:

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

---

## Configuration

Every setting is read from the environment. Nothing is hard-coded.

| Variable | Default | Description |
| --- | --- | --- |
| `ADMIN_USERNAME` | `Arafat` | Administrator user name. |
| `ADMIN_PASSWORD` | — | Administrator password (plain, read server side only). |
| `ADMIN_PASSWORD_HASH` | — | Optional PBKDF2 hash instead of the plain password. |
| `SECRET_KEY` | random (dev) | Signs the session cookie. **Required in production.** |
| `MAX_UPLOAD_MB` | `5` | Maximum upload size in megabytes. |
| `MAX_DIMENSION` | `8000` | Maximum width/height in pixels. |
| `DATA_DIR` | `./data` | Directory for the SQLite database (volume mount on Railway). |
| `DB_PATH` | `$DATA_DIR/urbg.db` | Full path of the database file. |
| `MODEL_DIR` | `./models` | Where the ONNX models are cached. |
| `ENVIRONMENT` | `development` | `production` enables secure cookies and requires `SECRET_KEY`. |
| `SESSION_MAX_AGE_MINUTES` | `480` | Administrator session lifetime (8 hours). |
| `COOKIE_SECURE` | `true` in production | Sets the `Secure` flag on the session cookie. |
| `COOKIE_SAMESITE` | `lax` | `SameSite` attribute of the session cookie. |
| `CSRF_PROTECT` | `true` | Require the `X-CSRF-Token` header on admin mutations. |
| `LOGIN_MAX_ATTEMPTS` | `5` | Failed logins before the account is locked. |
| `LOGIN_WINDOW_SECONDS` | `900` | Window used to count failed logins. |
| `LOGIN_LOCKOUT_SECONDS` | `900` | How long a locked account stays locked. |
| `API_RATE_LIMIT_PER_MINUTE` | `0` (off) | Per-API-key request limit. |
| `REMBG_MODEL` | `u2netp` | Model used when the app boots. |
| `REMBG_PROVIDER` | `CPUExecutionProvider` | ONNX Runtime execution provider. |
| `ENGINE_WARMUP_ON_START` | `true` | Load the model in the background at start-up. |
| `CORS_ORIGINS` | empty | Comma separated browser origins allowed to call the API. |
| `PUBLIC_BASE_URL` | empty | Public URL used in the generated documentation snippets. |

---

## Running locally

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Then open <http://127.0.0.1:8000> — you are redirected to `/login`.

* User name: `Arafat`
* Password: the value of `ADMIN_PASSWORD` (`ARAFAT168642` by default)

On the first request the `u2netp` model (~4.7 MB) is downloaded into `models/`.
The dashboard shows the engine status and lets you pre-load it manually.

Useful endpoints while developing:

* <http://127.0.0.1:8000/health> – health check (used by Railway)
* <http://127.0.0.1:8000/api/docs> – interactive OpenAPI documentation
* <http://127.0.0.1:8000/login> – admin login

---

## Local testing

```bash
pytest tests -v
```

The suite (30 tests) covers authentication, rate limiting, CSRF, API key
lifecycle, usage tracking, the multipart/base64/raw upload paths, colour
removal, validation errors and the dashboard data endpoints. The AI-dependent
tests are skipped automatically when the model cannot be downloaded.

Manual smoke test with a key:

```bash
# 1. Log in and create a key (the dashboard is the easiest way),
#    or via the API:
curl -c cookies.txt -X POST http://127.0.0.1:8000/admin/api/login \
  -H "Content-Type: application/json" \
  -d '{"username":"Arafat","password":"ARAFAT168642"}'

# 2. Use the key
curl -X POST http://127.0.0.1:8000/api/v1/remove \
  -H "X-API-Key: YOUR_API_KEY" \
  -F "file=@photo.jpg" \
  --output result.png
```

---

## Railway deployment

### 1. Create the service

1. Push this repository to GitHub.
2. In Railway: **New Project → Deploy from GitHub repo** → pick the repository.
3. Railway detects the `Dockerfile` and builds it automatically.

### 2. Add a persistent volume

1. Open the service → **Volumes** → **+ Add Volume**.
2. Mount path: `/data`
3. Railway creates the volume and mounts it into the container.

The SQLite database lives at `/data/urbg.db` (`DATA_DIR=/data`), so it survives
redeploys and restarts. The container never relies on temporary files for
permanent data.

### 3. Set the environment variables

Service → **Variables** → add:

| Variable | Value |
| --- | --- |
| `ADMIN_USERNAME` | `Arafat` |
| `ADMIN_PASSWORD` | `ARAFAT168642` |
| `SECRET_KEY` | a long random value (see below) |
| `MAX_UPLOAD_MB` | `5` |
| `ENVIRONMENT` | `production` |
| `PUBLIC_BASE_URL` | `https://<your-domain>.up.railway.app` (optional, used in the docs) |

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

> `ENVIRONMENT=production` turns on the `Secure` cookie flag, so the dashboard
> must be opened over HTTPS (Railway provides TLS automatically). Keep
> `COOKIE_SECURE=false` only for plain-HTTP local testing.

### 4. Deploy

Railway builds the image (the `u2netp` model is downloaded **during the build**,
so the first request is fast), then starts the container with:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1 --proxy-headers --forwarded-allow-ips '*'
```

`$PORT` is injected by Railway. The health check is configured in
`railway.json`:

```json
"healthcheckPath": "/health",
"healthcheckTimeout": 120
```

A single worker is used on purpose: it keeps one ONNX session in memory and
serialises SQLite writes. Scale with more replicas if you need more throughput.

### 5. Verify the deployment

```bash
curl https://<your-domain>.up.railway.app/health
```

```json
{
  "status": "ok",
  "service": "UrBG Remover",
  "version": "1.0.0",
  "engine": { "model": "u2netp", "ready": true, "error": null }
}
```

Open the same URL in a browser → you land on the login page.

### 6. Optional: model cache on the volume

By default the models live inside the image (`/app/models`). To persist larger
models (e.g. `u2net`, 176 MB) across redeploys, add:

```env
MODEL_DIR=/data/models
```

The entrypoint copies the baked-in model onto the volume the first time it runs.

---

## REST API reference

All endpoints except `/health` require the API key in the `X-API-Key` header
(`Authorization: Bearer <key>` also works).

Errors are always JSON:

```json
{ "error": { "code": "invalid_api_key", "message": "The supplied API key is invalid or revoked.", "details": {} } }
```

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| `GET` | `/health` | none | Service + engine health (used by Railway). |
| `GET` | `/api/v1/status` | API key | Version, limits and AI engine status. |
| `POST` | `/api/v1/remove` | API key | Upload an image (multipart or raw body) and get a transparent PNG. |
| `POST` | `/api/v1/remove/url` | API key | Download a public image by URL and process it. |
| `POST` | `/api/v1/remove/base64` | API key | Process a base64 / data-URL image. |
| `POST` | `/api/v1/remove/color` | API key | Remove a solid background colour (chroma key). |
| `GET` | `/api/v1/usage` | API key | Usage counters for the calling key. |

### `POST /api/v1/remove`

Accepts `multipart/form-data` (field `file`, `image` or `upload`) or a raw image
body.

| Query parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `format` | string | `png` | `png`, `webp` or `jpeg`. |
| `response_format` | string | `binary` | `binary` (image bytes) or `json` (base64 payload). |
| `alpha_matting` | bool | `false` | Smoother edges (slower). |
| `post_process_mask` | bool | `false` | Guided-filter mask refinement. |
| `only_mask` | bool | `false` | Return only the alpha mask. |
| `bgcolor` | string | — | Flatten onto a hex colour, e.g. `#ffffff`. |

```bash
curl -X POST https://<domain>/api/v1/remove \
  -H "X-API-Key: YOUR_API_KEY" \
  -F "file=@photo.jpg" \
  --output result.png
```

### `POST /api/v1/remove/url`

```json
{ "url": "https://example.com/photo.jpg", "format": "png", "alpha_matting": false }
```

Only `http`/`https` is allowed and every hostname is resolved and checked
against private, loopback, link-local and reserved ranges (SSRF protection).

### `POST /api/v1/remove/base64`

```json
{ "image": "<base64>" }
```

A full data URL (`data:image/png;base64,...`) is accepted as well.

### `POST /api/v1/remove/color`

```json
{ "image": "<base64>", "color": "#ffffff", "tolerance": 20, "softness": 10 }
```

`tolerance` (0–100) controls how far a pixel may deviate from the target
colour, `softness` (0–100) feathers the edge.

### `GET /api/v1/usage?days=30`

Returns the totals for the calling key plus a daily series.

---

## Integration examples

The **Integrations** page inside the dashboard renders copy-ready snippets with
your live base URL for:

* PHP (cURL)
* HTML + JavaScript (Fetch API)
* React (TypeScript)
* Flutter (Dart HTTP)
* Python (Requests)
* Secure backend proxy (Node.js) — the recommended pattern for web apps

> **Never ship your API key to a browser or a mobile app.** Anything in public
> JavaScript, a React bundle or a Flutter binary can be extracted. Put the key
> in a server-side environment variable and proxy the request through your own
> backend, exactly like the `proxy.js` example.

---

## Security model

* The administrator password is read from `ADMIN_PASSWORD` (or
  `ADMIN_PASSWORD_HASH`) and never reaches the frontend.
* Passwords are verified with PBKDF2-HMAC-SHA256 (260 000 iterations) in
  constant time.
* The session is a signed cookie (`itsdangerous`): `HttpOnly`, `Secure` in
  production, `SameSite=Lax`, with a server side expiry check.
* Every state-changing admin request must carry the `X-CSRF-Token` header.
* Failed logins are counted per IP + user name; after 5 failures the account
  is locked for 15 minutes.
* API keys are generated with `secrets.token_urlsafe`, stored only as a
  SHA-256 hash and displayed exactly once.
* Uploads are size limited, dimension limited and validated by magic bytes
  before they reach the model; the multipart body is parsed in memory so no
  temporary files are created.
* Remote downloads are size limited and blocked for private networks.
* Errors never leak internal stack traces to API clients.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `503 engine_unavailable` | The model could not be loaded. Check the dashboard → AI engine, or click **Pre-load model**. The first load downloads ~4.7 MB from GitHub. |
| Login returns `429` | The account is locked after too many failed attempts. Wait for `LOGIN_LOCKOUT_SECONDS` or restart the container. |
| Dashboard redirects to `/login` in a loop | The cookie is `Secure` but you are using plain HTTP. Set `COOKIE_SECURE=false` for local HTTP testing. |
| `SECRET_KEY must be set in production` | Set `SECRET_KEY` in the Railway variables. |
| Data lost after a redeploy | The volume is not mounted at `/data`. Add it in Railway → Volumes and set `DATA_DIR=/data`. |
| SQLite `database is locked` | Another process is writing. Keep `--workers 1` (the default) and do not scale the container horizontally against the same volume. |
| Model download fails during the build | The build needs internet access to `github.com/danielgatis/rembg`. Retry the build, or set `MODEL_CHECKSUM_DISABLED=1` if GitHub is rate limiting you. |

---

## License

Personal project — use it, change it, host it yourself.
