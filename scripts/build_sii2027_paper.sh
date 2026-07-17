#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
PAPER_DIR="$ROOT/paper/sii2027"
LOG_DIR="$ROOT/artifacts/sii2027/logs/paper_build"
mkdir -p "$LOG_DIR"

if [ -z "${SOURCE_DATE_EPOCH:-}" ]; then
  SOURCE_DATE_EPOCH="$(
    python3 - "$ROOT/artifacts/sii2027/results/summary.json" <<'PY' || true
import datetime as _dt
import json
import sys

path = sys.argv[1]
try:
    created_at = json.loads(open(path, encoding="utf-8").read()).get("created_at", "")
    parsed = _dt.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    print(int(parsed.timestamp()))
except Exception:
    print("0")
PY
  )"
fi
export SOURCE_DATE_EPOCH="${SOURCE_DATE_EPOCH:-0}"
export FORCE_SOURCE_DATE="${FORCE_SOURCE_DATE:-1}"

if [ ! -f "$PAPER_DIR/main.tex" ]; then
  echo "SII 2027 paper source is missing: paper/sii2027/main.tex" | tee "$LOG_DIR/build.log"
  exit 2
fi

mkdir -p "$PAPER_DIR/generated" "$PAPER_DIR/figures"
cp "$ROOT"/artifacts/sii2027/tables/*.tex "$PAPER_DIR/generated/"
cp "$ROOT"/artifacts/sii2027/figures/*.pdf "$PAPER_DIR/figures/"

cd "$PAPER_DIR"
pdflatex -interaction=nonstopmode -halt-on-error main.tex | tee "$LOG_DIR/pdflatex-1.log"
if grep -q '\\bibliography' main.tex; then
  bibtex main | tee "$LOG_DIR/bibtex.log"
  pdflatex -interaction=nonstopmode -halt-on-error main.tex | tee "$LOG_DIR/pdflatex-2.log"
  pdflatex -interaction=nonstopmode -halt-on-error main.tex | tee "$LOG_DIR/pdflatex-3.log"
else
  pdflatex -interaction=nonstopmode -halt-on-error main.tex | tee "$LOG_DIR/pdflatex-2.log"
fi
cp main.pdf "$ROOT/wod2sim.pdf"
rm -f main.pdf paper.pdf

find "$LOG_DIR" -maxdepth 1 -type f -name '*.log' -exec perl -pi -e 's/[ \t]+$//' {} +
