#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UV_BIN="${UV_BIN:-$(command -v uv || true)}"
ALPASIM_ROOT="${ALPASIM_ROOT:-$ROOT/workspace/alpasim}"
TORCH_PACKAGE="${TORCH_PACKAGE:-torch==2.11.0+cu129}"
TORCH_INDEX_URL="${TORCH_INDEX_URL:-https://download.pytorch.org/whl/cu129}"

if [[ -z "$UV_BIN" ]]; then
  echo "uv is required. Install it first, e.g. python3 -m pip install --user uv" >&2
  exit 1
fi

mkdir -p "$ROOT/.uv-cache"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  env UV_CACHE_DIR="$ROOT/.uv-cache" "$UV_BIN" venv "$ROOT/.venv"
fi

env UV_CACHE_DIR="$ROOT/.uv-cache" "$UV_BIN" pip install \
  --python "$ROOT/.venv/bin/python" \
  -e "$ROOT[alpasim]"

env UV_CACHE_DIR="$ROOT/.uv-cache" "$UV_BIN" pip install \
  --python "$ROOT/.venv/bin/python" \
  --index-url "$TORCH_INDEX_URL" \
  "$TORCH_PACKAGE"

if [[ -d "$ALPASIM_ROOT/src/driver" ]]; then
  ALPASIM_ROOT="$ALPASIM_ROOT" "$ROOT/.venv/bin/python" "$ROOT/scripts/setup_alpasim_local_plugin.py"
else
  echo "Repo .venv is ready at $ROOT/.venv"
  echo "If you do not already have an AlpaSim checkout, run:"
  echo "  ./scripts/bootstrap_alpasim_checkout.sh"
  echo "If you already have one, set ALPASIM_ROOT and run:"
  echo "  ALPASIM_ROOT=<path> ./.venv/bin/python scripts/setup_alpasim_local_plugin.py"
fi
