#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ALPASIM_ROOT="${ALPASIM_ROOT:-$ROOT/workspace/alpasim}"
ALPASIM_UPSTREAM_URL="${ALPASIM_UPSTREAM_URL:-https://github.com/NVlabs/alpasim.git}"
ALPASIM_UPSTREAM_REF="${ALPASIM_UPSTREAM_REF:-affc2eab209fa43bdfa2f26c0f8d437922d78a68}"
STAMP="$(date +%Y%m%d_%H%M%S)"

checkout_ref() {
  local current_ref requested_ref
  current_ref="$(git -C "$ALPASIM_ROOT" rev-parse HEAD)"
  echo "Fetching AlpaSim ref $ALPASIM_UPSTREAM_REF"
  git -C "$ALPASIM_ROOT" fetch --depth 1 origin "$ALPASIM_UPSTREAM_REF"
  requested_ref="$(git -C "$ALPASIM_ROOT" rev-parse FETCH_HEAD)"

  if [[ "$current_ref" == "$requested_ref" ]]; then
    echo "Using AlpaSim checkout at $ALPASIM_ROOT ($ALPASIM_UPSTREAM_REF)"
    return
  fi
  if [[ -n "$(git -C "$ALPASIM_ROOT" status --porcelain)" ]]; then
    echo "AlpaSim checkout is not at $ALPASIM_UPSTREAM_REF and has local changes: $ALPASIM_ROOT" >&2
    echo "Commit or stash those changes, then rerun this script." >&2
    exit 1
  fi
  echo "Updating $ALPASIM_ROOT to $ALPASIM_UPSTREAM_REF"
  git -C "$ALPASIM_ROOT" checkout --detach "$requested_ref"
}

clone_checkout() {
  echo "Cloning $ALPASIM_UPSTREAM_URL @ $ALPASIM_UPSTREAM_REF into $ALPASIM_ROOT"
  git clone --filter=blob:none --no-checkout "$ALPASIM_UPSTREAM_URL" "$ALPASIM_ROOT"
  git -C "$ALPASIM_ROOT" fetch --depth 1 origin "$ALPASIM_UPSTREAM_REF"
  git -C "$ALPASIM_ROOT" checkout --detach FETCH_HEAD
}

if [[ -d "$ALPASIM_ROOT/.git" && -f "$ALPASIM_ROOT/pyproject.toml" && -d "$ALPASIM_ROOT/src/driver" && -d "$ALPASIM_ROOT/src/wizard" ]]; then
  checkout_ref
elif [[ -d "$ALPASIM_ROOT/src/driver" && -d "$ALPASIM_ROOT/src/wizard" ]]; then
  backup_path="${ALPASIM_ROOT}.invalid.${STAMP}"
  echo "ALPASIM_ROOT looks like a copied AlpaSim tree without git metadata: $ALPASIM_ROOT" >&2
  echo "Moving it aside to $backup_path and recloning a real checkout." >&2
  mv "$ALPASIM_ROOT" "$backup_path"
  clone_checkout
else
  if [[ -e "$ALPASIM_ROOT" && -n "$(find "$ALPASIM_ROOT" -mindepth 1 -maxdepth 1 2>/dev/null)" ]]; then
    echo "ALPASIM_ROOT exists but is not a usable checkout: $ALPASIM_ROOT" >&2
    echo "Expected a real git checkout with .git, pyproject.toml, src/driver, and src/wizard; or an empty directory." >&2
    exit 1
  fi
  rm -rf "$ALPASIM_ROOT"
  clone_checkout
fi

export ALPASIM_ROOT
if [[ "${ALPASIM_SKIP_ENV_SETUP:-0}" != "1" ]]; then
  "$ROOT/scripts/bootstrap_alpasim_env.sh"
fi
