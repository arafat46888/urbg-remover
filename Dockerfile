# syntax=docker/dockerfile:1
#
# UrBG Remover - production image
# ---------------------------------------------------------------------------
# Single container that serves:
#   * the FastAPI REST API  (/api/v1/*)
#   * the private admin dashboard (/, /login)
#   * the rembg ONNX model (baked into the image, CPU only)
# ---------------------------------------------------------------------------

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# curl is used by the container health check; the GL libraries are required by
# opencv (a rembg dependency).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        libglib2.0-0 \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

# --- Python dependencies ---------------------------------------------------
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# --- Bake the default ONNX model into the image ----------------------------
# The model is downloaded at build time so the first request does not have to
# wait for it.  Newer/larger models can still be selected from the dashboard
# and are downloaded on demand.
ENV U2NET_HOME=/app/models \
    MODEL_DIR=/app/models
RUN mkdir -p /app/models \
    && python -c "\
import os;\
os.environ['U2NET_HOME'] = '/app/models';\
from rembg import new_session;\
session = new_session('u2netp', providers=['CPUExecutionProvider']);\
print('baked model:', session.model_name)"

# --- Application code ------------------------------------------------------
COPY app ./app
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Persistent data lives on the Railway volume (mounted at /data).
ENV DATA_DIR=/data \
    DB_PATH=/data/urbg.db \
    PORT=8000 \
    ENVIRONMENT=production
RUN mkdir -p /data /app/models

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/health" || exit 1

ENTRYPOINT ["/app/docker-entrypoint.sh"]
