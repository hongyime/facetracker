#!/usr/bin/env bash
# Smoke 10 driver: boot the app via uvicorn inside a docker container, probe /health,
# verify reaper drains a real outbox row, then tear down.
#
# Runs from host. Requires postgres on facetracker-net.
set -euo pipefail
export MSYS_NO_PATHCONV=1
export MSYS2_ARG_CONV_EXCL='*'

CONTAINER_NAME="facetracker-smoke10"

# Host-side temp dirs (FAISS, smoke logs)
TMP_FAISS="$(mktemp -d -t smoke10_faiss_XXXX)"
TMP_LOG="$(mktemp -t smoke10_log_XXXX.log)"
echo "[host] tmp_faiss=$TMP_FAISS"
echo "[host] tmp_log=$TMP_LOG"

cleanup() {
    echo "[host] cleanup..."
    docker rm -f "$CONTAINER_NAME" 2>/dev/null || true
    rm -rf "$TMP_FAISS" || true
    rm -f "$TMP_LOG" || true
}
trap cleanup EXIT

# Boot uvicorn in background container
docker run -d --rm --name "$CONTAINER_NAME" \
    --network facetracker-net \
    -w /app \
    -v "$(pwd -W 2>/dev/null || pwd)/src:/app/src:ro" \
    -v "$(pwd -W 2>/dev/null || pwd)/config:/app/config:ro" \
    -v "$(pwd -W 2>/dev/null || pwd)/smoke_tests:/app/smoke_tests:ro" \
    -v facetracker-insightface-cache:/root/.insightface \
    --env-file .env \
    -e FACE_STORAGE_ROOT=/tmp/smoke10_faiss \
    -e HOST_FACE_STORAGE=/tmp/smoke10_faiss \
    -p 18000:8000 \
    facetracker-api:latest \
    sh -c "mkdir -p /tmp/smoke10_faiss/embeddings/live /tmp/smoke10_faiss/embeddings/staging && uvicorn src.main:app --host 0.0.0.0 --port 8000"

echo "[host] container starting, polling /health for up to 300s (first run downloads insightface model ~280MB)..."
DEADLINE=$((SECONDS + 300))
HEALTH=""
while [ $SECONDS -lt $DEADLINE ]; do
    if HEALTH=$(curl -fsS http://localhost:18000/health 2>/dev/null); then
        echo "[host] /health = $HEALTH"
        break
    fi
    sleep 1
done

if [ -z "$HEALTH" ]; then
    echo "[host] /health never responded. Container logs:"
    docker logs "$CONTAINER_NAME" 2>&1 | tail -50
    exit 10
fi

# Confirm reaper thread is alive (via behavior, not introspection — docker exec
# spawns a different process, can't see uvicorn's threads directly).
echo "[host] verifying reaper drains an injected outbox row in <5s..."
docker exec "$CONTAINER_NAME" python -u -m smoke_tests.smoke10_inject_one

echo "[host] shutting down container gracefully (SIGTERM, lifespan teardown)..."
docker stop "$CONTAINER_NAME"

echo "PASS"
