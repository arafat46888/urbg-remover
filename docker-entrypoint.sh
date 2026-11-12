#!/bin/sh
# UrBG Remover container entrypoint.
# ---------------------------------------------------------------------------
# Prepares the persistent directories and starts the production server.
# The PORT variable is provided by Railway.

set -e

PORT="${PORT:-8000}"
DATA_DIR="${DATA_DIR:-/data}"
MODEL_DIR="${MODEL_DIR:-/app/models}"

export DATA_DIR
export MODEL_DIR
export U2NET_HOME="${U2NET_HOME:-$MODEL_DIR}"

mkdir -p "$DATA_DIR" "$MODEL_DIR"

# If the models directory points at the persistent volume, copy the model that
# was baked into the image over to it (only once).
if [ "$MODEL_DIR" != "/app/models" ] && [ -d /app/models ]; then
    for model in /app/models/*.onnx; do
        [ -e "$model" ] || continue
        if [ ! -f "$MODEL_DIR/$(basename "$model")" ]; then
            echo "Copying model $(basename "$model") to $MODEL_DIR"
            cp "$model" "$MODEL_DIR/"
        fi
    done
fi

echo "UrBG Remover starting on port ${PORT} (data=${DATA_DIR}, models=${MODEL_DIR})"

# A single worker keeps one ONNX session in memory and serialises SQLite
# writes.  Scale with more replicas instead of more workers.
exec uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT}" \
    --workers 1 \
    --proxy-headers \
    --forwarded-allow-ips '*' \
    --no-server-header \
    --log-level info
