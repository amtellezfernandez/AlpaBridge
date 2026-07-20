#!/usr/bin/env bash
set -u

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
cd "$ROOT"

OUT="artifacts/cvm"
mkdir -p "$OUT/environment" "$OUT/logs/baseline" "$OUT/reports"

REPORT="$OUT/reports/repository_inventory.md"
if [ ! -f "$REPORT" ]; then
  echo "Missing tracked repository inventory: $REPORT" >&2
  exit 1
fi
if [ ! -f "wod2sim.pdf" ]; then
  echo "Missing paper artifact: wod2sim.pdf" >&2
  exit 1
fi

TEST_FILE_COUNT="$(find tests -maxdepth 1 -type f -name 'test_*.py' | wc -l | tr -d '[:space:]')"
PDF_SIZE="$(wc -c < wod2sim.pdf | tr -d '[:space:]')"
WOD2SIM_TEST_FILE_COUNT="$TEST_FILE_COUNT" \
  WOD2SIM_PDF_SIZE="$PDF_SIZE" \
  perl -0pi -e '
    s/(PDF size at audit:\s*)\d+(\s+bytes\.)/$1$ENV{"WOD2SIM_PDF_SIZE"}$2/;
    s/(Test directory:\s*`tests`\s+with\s*)\d+(\s+top-level test files\.)/$1$ENV{"WOD2SIM_TEST_FILE_COUNT"}$2/;
  ' "$REPORT"

if ! grep -Fq "PDF size at audit: ${PDF_SIZE} bytes." "$REPORT"; then
  echo "Failed to refresh the PDF size in $REPORT" >&2
  exit 1
fi
if ! grep -Fq 'Test directory: `tests` with '"${TEST_FILE_COUNT}"' top-level test files.' "$REPORT"; then
  echo "Failed to refresh the test-file count in $REPORT" >&2
  exit 1
fi

redact() {
  local host
  host="$(hostname 2>/dev/null || true)"
  WOD2SIM_REDACT_ROOT="$ROOT" \
    WOD2SIM_REDACT_HOME="${HOME:-/home/user}" \
    WOD2SIM_REDACT_HOST="$host" \
    perl -pe '
      BEGIN {
        $root = quotemeta($ENV{"WOD2SIM_REDACT_ROOT"} // "");
        $home = quotemeta($ENV{"WOD2SIM_REDACT_HOME"} // "");
        $host = quotemeta($ENV{"WOD2SIM_REDACT_HOST"} // "");
      }
      s/$root/<repo>/g if length $root;
      s/$home/~/g if length $home;
      s/$host/<host>/g if length $host;
      s/^ ID: [0-9a-fA-F-]{36}$/ ID: <docker-engine-id>/;
    '
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
  echo "command=git ls-files | sort"
  echo "captured_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  git ls-files | sort
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

if [ -n "${PYTHON:-}" ]; then
  PYTHON_CMD_TEXT="$PYTHON"
elif command -v uv >/dev/null 2>&1; then
  PYTHON_CMD_TEXT="uv run python"
else
  PYTHON_CMD_TEXT="python3"
fi
read -r -a PYTHON_CMD <<< "$PYTHON_CMD_TEXT"
{
  echo "# Python environment"
  echo "captured_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo
  echo "## $PYTHON_CMD_TEXT --version"
  "${PYTHON_CMD[@]}" --version 2>&1 || true
  echo
  echo "## $PYTHON_CMD_TEXT -m pip --version"
  "${PYTHON_CMD[@]}" -m pip --version 2>&1 || true
  echo
  echo "## $PYTHON_CMD_TEXT -m pip list --format=freeze"
  "${PYTHON_CMD[@]}" -m pip list --format=freeze 2>&1 || true
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
