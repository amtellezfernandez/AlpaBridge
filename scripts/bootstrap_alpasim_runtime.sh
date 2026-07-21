#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"
export ALPASIM_ROOT="${ALPASIM_ROOT:-$ROOT/workspace/alpasim}"

if [[ -f "$ROOT/.env.alpasim_hf" ]]; then
  # shellcheck disable=SC1091
  source "$ROOT/.env.alpasim_hf"
fi

"$ROOT/scripts/bootstrap_alpasim_checkout.sh"
"$ROOT/.venv/bin/python" "$ROOT/scripts/check_alpasim_readiness.py" --skip-image
"$ROOT/scripts/build_alpasim_base_image.sh"
"$ROOT/.venv/bin/python" "$ROOT/scripts/check_alpasim_readiness.py"
