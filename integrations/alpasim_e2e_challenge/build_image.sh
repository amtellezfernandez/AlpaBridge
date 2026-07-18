#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
IMAGE="${IMAGE:-alpasim-e2e-wod2sim:latest}"
ALPASIM_ROOT="${ALPASIM_ROOT:-$ROOT/workspace/alpasim}"
ALPASIM_GRPC_ROOT="${ALPASIM_GRPC_ROOT:-$ALPASIM_ROOT/src/grpc}"

if [[ ! -d "$ALPASIM_GRPC_ROOT/alpasim_grpc" ]]; then
  echo "Expected AlpaSim gRPC package at: $ALPASIM_GRPC_ROOT/alpasim_grpc" >&2
  echo "Set ALPASIM_ROOT or ALPASIM_GRPC_ROOT to an AlpaSim challenge checkout." >&2
  exit 2
fi

cd "$ROOT"
docker buildx build \
  --build-context "alpasim_grpc=$ALPASIM_GRPC_ROOT" \
  -f integrations/alpasim_e2e_challenge/Dockerfile \
  -t "$IMAGE" \
  .

echo "Built $IMAGE"

