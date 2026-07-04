#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export ALPASIM_ROOT="${ALPASIM_ROOT:-$ROOT/workspace/alpasim}"
IMAGE_TAG="${ALPASIM_BASE_IMAGE_TAG:-alpasim-base:0.66.0}"
LOCK_DIR="${ALPASIM_ROOT}/.build-alpasim-base-image.lock"
DOCKER_PROGRESS="${ALPASIM_DOCKER_PROGRESS:-auto}"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "Repo virtualenv is missing at $ROOT/.venv." >&2
  echo "Run ./scripts/bootstrap_alpasim_env.sh first." >&2
  exit 1
fi

"$ROOT/.venv/bin/python" - <<'PY'
from scripts.run_alpasim_local_external import _preflight_platform_compatibility
_preflight_platform_compatibility()
PY

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required to build ${IMAGE_TAG}" >&2
  exit 1
fi

if [[ ! -d "$ALPASIM_ROOT" || ! -f "$ALPASIM_ROOT/Dockerfile" ]]; then
  echo "ALPASIM_ROOT does not look like a valid checkout: $ALPASIM_ROOT" >&2
  echo "Run ./scripts/bootstrap_alpasim_checkout.sh first." >&2
  exit 1
fi

if docker image inspect "$IMAGE_TAG" >/dev/null 2>&1; then
  echo "Using existing image $IMAGE_TAG"
  exit 0
fi

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
  echo "Another build for $IMAGE_TAG appears to be running." >&2
  echo "Wait for it to finish or remove $LOCK_DIR if the previous build crashed." >&2
  exit 1
fi

cleanup() {
  rmdir "$LOCK_DIR" >/dev/null 2>&1 || true
}

trap cleanup EXIT

echo "Building $IMAGE_TAG from $ALPASIM_ROOT"
cd "$ALPASIM_ROOT"
docker build --progress="$DOCKER_PROGRESS" -t "$IMAGE_TAG" .
