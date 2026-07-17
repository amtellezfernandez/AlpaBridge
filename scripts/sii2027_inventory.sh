#!/usr/bin/env bash
set -u

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

OUT="artifacts/sii2027"
mkdir -p "$OUT/environment" "$OUT/logs/baseline" "$OUT/reports"

redact() {
  sed "s#${ROOT}#<repo>#g; s#${HOME:-/home/user}#~#g"
}

{
  echo "# Git state"
  echo "captured_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo "## pwd"
  pwd
  echo
  echo "## git rev-parse --show-toplevel"
  git rev-parse --show-toplevel
  echo
  echo "## git status --short"
  git status --short
  echo
  echo "## note"
  echo "This status is captured before committing regenerated artifacts; the publish state is the Git commit containing this file."
  echo
  echo "## git rev-parse HEAD"
  git rev-parse HEAD
  echo
  echo "## git submodule status --recursive"
  git submodule status --recursive
} | redact > "$OUT/environment/git_state.txt"

{
  echo "command=find . -maxdepth 3 -type f | sort"
  echo "captured_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  find . -maxdepth 3 -type f | sort
} | redact > "$OUT/logs/baseline/find_maxdepth3.log"

{
  echo "# System environment"
  echo "captured_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo "## uname -a"
  uname -a
  echo
  echo "## lscpu"
  if command -v lscpu >/dev/null 2>&1; then lscpu; else echo "lscpu unavailable"; fi
  echo
  echo "## docker version"
  if command -v docker >/dev/null 2>&1; then docker version 2>&1; else echo "docker unavailable"; fi
  echo
  echo "## docker info"
  if command -v docker >/dev/null 2>&1; then docker info 2>&1; else echo "docker unavailable"; fi
  echo
  echo "## nvidia-smi"
  if command -v nvidia-smi >/dev/null 2>&1; then nvidia-smi 2>&1; else echo "nvidia-smi unavailable"; fi
} | redact > "$OUT/environment/system.txt"

PYTHON_BIN="${PYTHON:-./.venv/bin/python}"
{
  echo "# Python environment"
  echo "captured_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo "## $PYTHON_BIN --version"
  "$PYTHON_BIN" --version 2>&1 || true
  echo
  echo "## $PYTHON_BIN -m pip --version"
  "$PYTHON_BIN" -m pip --version 2>&1 || true
  echo
  echo "## $PYTHON_BIN -m pip list --format=freeze"
  "$PYTHON_BIN" -m pip list --format=freeze 2>&1 || true
} | redact > "$OUT/environment/python_packages.txt"

{
  echo "# Simulator state"
  echo "captured_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  for path in workspace/alpasim workspace/alpasim-clean; do
    echo
    echo "## $path"
    if git -C "$path" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      echo "head=$(git -C "$path" rev-parse HEAD 2>&1)"
      echo "status:"
      git -C "$path" status --short 2>&1
    else
      echo "missing git checkout"
    fi
  done
  echo
  echo "## docker images --digests"
  if command -v docker >/dev/null 2>&1; then
    docker images --digests --format '{{.Repository}}:{{.Tag}} {{.Digest}} {{.ID}} {{.Size}}' | sort
  else
    echo "docker unavailable"
  fi
  echo
  echo "## local scene assets"
  find workspace -path '*local-usdz*' -maxdepth 6 -type f 2>/dev/null | sort | sed 's#^#asset_file=#' | head -200
} | redact > "$OUT/environment/simulator_state.txt"

find "$OUT/environment" -type f -name '*.txt' -exec perl -pi -e 's/[ \t]+$//' {} +
find "$OUT/logs/baseline" -maxdepth 1 -type f -name '*.log' -exec perl -pi -e 's/[ \t]+$//' {} +

echo "Inventory refreshed under $OUT"
