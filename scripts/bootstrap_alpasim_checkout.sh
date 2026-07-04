#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ALPASIM_ROOT="${ALPASIM_ROOT:-$ROOT/workspace/alpasim}"
ALPASIM_UPSTREAM_URL="${ALPASIM_UPSTREAM_URL:-https://github.com/NVlabs/alpasim.git}"
ALPASIM_UPSTREAM_REF="${ALPASIM_UPSTREAM_REF:-v2026.4}"
STAMP="$(date +%Y%m%d_%H%M%S)"

if [[ -d "$ALPASIM_ROOT/.git" && -f "$ALPASIM_ROOT/pyproject.toml" && -d "$ALPASIM_ROOT/src/driver" && -d "$ALPASIM_ROOT/src/wizard" ]]; then
  echo "Using existing AlpaSim checkout at $ALPASIM_ROOT"
elif [[ -d "$ALPASIM_ROOT/src/driver" && -d "$ALPASIM_ROOT/src/wizard" ]]; then
  backup_path="${ALPASIM_ROOT}.invalid.${STAMP}"
  echo "ALPASIM_ROOT looks like a copied AlpaSim tree without git metadata: $ALPASIM_ROOT" >&2
  echo "Moving it aside to $backup_path and recloning a real checkout." >&2
  mv "$ALPASIM_ROOT" "$backup_path"
  echo "Cloning $ALPASIM_UPSTREAM_URL @ $ALPASIM_UPSTREAM_REF into $ALPASIM_ROOT"
  git clone --branch "$ALPASIM_UPSTREAM_REF" --depth 1 "$ALPASIM_UPSTREAM_URL" "$ALPASIM_ROOT"
else
  if [[ -e "$ALPASIM_ROOT" && -n "$(find "$ALPASIM_ROOT" -mindepth 1 -maxdepth 1 2>/dev/null)" ]]; then
    echo "ALPASIM_ROOT exists but is not a usable checkout: $ALPASIM_ROOT" >&2
    echo "Expected a real git checkout with .git, pyproject.toml, src/driver, and src/wizard; or an empty directory." >&2
    exit 1
  fi
  rm -rf "$ALPASIM_ROOT"
  echo "Cloning $ALPASIM_UPSTREAM_URL @ $ALPASIM_UPSTREAM_REF into $ALPASIM_ROOT"
  git clone --branch "$ALPASIM_UPSTREAM_REF" --depth 1 "$ALPASIM_UPSTREAM_URL" "$ALPASIM_ROOT"
fi

export ALPASIM_ROOT
"$ROOT/scripts/bootstrap_alpasim_env.sh"
