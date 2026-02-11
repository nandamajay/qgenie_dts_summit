#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-8080}"
IMAGE="qgenie/phase1:fixed"
NAME="qgenie_phase1"

# Build image
docker build -t "$IMAGE" .

# Persist clones
mkdir -p ./work/projects

# Run (clean previous)
docker rm -f "$NAME" >/dev/null 2>&1 || true

docker run --name "$NAME" \
  -p "$PORT:8080" \
  -e PORT=8080 \
  -e WORK_DIR=/work \
  -v "$(pwd)/work:/work" \
  "$IMAGE"

echo "\nOpen http://localhost:$PORT"
