#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
STUDY_ROOT="${ALPABRIDGE_WAYMAX_STUDY_ROOT:-$ROOT/workspace/waymax-contract-study}"
WAYMAX_ROOT="$STUDY_ROOT/waymax"
VENV="$STUDY_ROOT/venv"
WAYMAX_REPOSITORY="https://github.com/waymo-research/waymax.git"
WAYMAX_COMMIT="a64dfec9be8576b60d9cecc94f406d9812d4a7d0"
OUTPUT="${ALPABRIDGE_WAYMAX_OUTPUT:-$ROOT/artifacts/external/waymax_contract_study}"

mkdir -p "$STUDY_ROOT"
if [ ! -d "$WAYMAX_ROOT/.git" ]; then
  git clone "$WAYMAX_REPOSITORY" "$WAYMAX_ROOT"
fi
git -C "$WAYMAX_ROOT" fetch --depth 1 origin "$WAYMAX_COMMIT"
git -C "$WAYMAX_ROOT" checkout --detach "$WAYMAX_COMMIT"

if [ ! -x "$VENV/bin/python" ]; then
  uv venv "$VENV" --python 3.12
fi
uv pip install --python "$VENV/bin/python" "$WAYMAX_ROOT"

export PYTHONPATH="$ROOT/src:$WAYMAX_ROOT${PYTHONPATH:+:$PYTHONPATH}"
export TF_CPP_MIN_LOG_LEVEL="${TF_CPP_MIN_LOG_LEVEL:-3}"
export TF_NUM_INTEROP_THREADS="${TF_NUM_INTEROP_THREADS:-1}"
export TF_NUM_INTRAOP_THREADS="${TF_NUM_INTRAOP_THREADS:-1}"
export XLA_FLAGS="${XLA_FLAGS:---xla_cpu_multi_thread_eigen=false}"

"$VENV/bin/python" -m alpabridge.experiments.waymax_contract_study \
  --waymax-root "$WAYMAX_ROOT" \
  --output "$OUTPUT"
