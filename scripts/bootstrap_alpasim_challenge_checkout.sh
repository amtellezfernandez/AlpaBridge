#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# The competition code is maintained on a separate upstream branch and does
# not exist in tagged/main AlpaSim releases. Keep its pin separate from the
# general-purpose simulator checkout used by bootstrap_alpasim_runtime.sh.
export ALPASIM_ROOT="${ALPASIM_ROOT:-$ROOT/workspace/alpasim-e2e}"
export ALPASIM_UPSTREAM_REF="${ALPASIM_UPSTREAM_REF:-20235345d7ea9eed5d5156099cf219cd35b2e4dc}"

"$ROOT/scripts/bootstrap_alpasim_checkout.sh"

if [[ ! -d "$ALPASIM_ROOT/e2e_challenge" ]]; then
  echo "AlpaSim ref $ALPASIM_UPSTREAM_REF does not contain e2e_challenge/." >&2
  exit 1
fi
