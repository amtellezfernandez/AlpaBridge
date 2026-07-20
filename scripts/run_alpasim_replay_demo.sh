#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
IMAGE="${IMAGE:-alpasim-e2e-wod2sim:latest}"
ALPASIM_ROOT="${ALPASIM_ROOT:-$ROOT/workspace/alpasim}"
OUTPUT_DIR="${OUTPUT_DIR:-$ROOT/artifacts/external/alpasim_protocol_replay}"
ASL_PATH="${ASL_PATH:-/tmp/alpasim-049f70-runtime-replay.asl}"
ALPASIM_COMMIT="049f70fbfe8207e1efd4831a6c3e78a38703d473"
ASL_SHA256="237d6b55f4da5b0610f1b8b1e940f52d9efdc9e39c8ca2b35c5b5285ebefdc1f"
ASL_URL="https://media.githubusercontent.com/media/NVlabs/alpasim/${ALPASIM_COMMIT}/src/runtime/tests/data/integration/rollout.asl"

mkdir -p "$OUTPUT_DIR/frames"
if [[ ! -f "$ASL_PATH" ]] || [[ "$(sha256sum "$ASL_PATH" | awk '{print $1}')" != "$ASL_SHA256" ]]; then
  curl -L --fail --silent --show-error --output "$ASL_PATH" "$ASL_URL"
fi
printf '%s  %s\n' "$ASL_SHA256" "$ASL_PATH" | sha256sum --check --status

ALPASIM_ROOT="$ALPASIM_ROOT" IMAGE="$IMAGE" \
  bash "$ROOT/integrations/alpasim_e2e_challenge/build_image.sh"

cleanup() {
  docker rm -f wod2sim-replay-full wod2sim-replay-command >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

run_arm() {
  local mode="$1"
  local port="$2"
  local name="$3"
  local extract_frames="$4"
  local telemetry="$OUTPUT_DIR/${mode}-telemetry.jsonl"
  local output="$OUTPUT_DIR/${mode}.json"

  rm -f "$telemetry" "$output"
  docker run --detach --rm \
    --name "$name" \
    --network host \
    --user "$(id -u):$(id -g)" \
    --env "ALPASIM_DRIVER_PORT=$port" \
    --env "WOD2SIM_GIT_HASH=$(git -C "$ROOT" rev-parse HEAD)" \
    --env "WOD2SIM_ROUTE_CONTRACT_MODE=$mode" \
    --env "WOD2SIM_CHALLENGE_TELEMETRY_PATH=/output/${mode}-telemetry.jsonl" \
    --volume "$OUTPUT_DIR:/output" \
    "$IMAGE" >/dev/null

  local frame_args=()
  if [[ "$extract_frames" == "true" ]]; then
    rm -f "$OUTPUT_DIR"/frames/*
    frame_args=(--frame-dir /output/frames)
  fi
  docker run --rm \
    --network host \
    --user "$(id -u):$(id -g)" \
    --entrypoint python \
    --volume "$ASL_PATH:/input.asl:ro" \
    --volume "$OUTPUT_DIR:/output" \
    --volume "$ROOT/scripts:/scripts:ro" \
    "$IMAGE" \
    /scripts/run_alpasim_replay_client.py \
    --asl /input.asl \
    --endpoint "127.0.0.1:$port" \
    --mode "$mode" \
    --output "/output/${mode}.json" \
    --source-url "$ASL_URL" \
    --alpasim-commit "$ALPASIM_COMMIT" \
    --expected-asl-sha256 "$ASL_SHA256" \
    "${frame_args[@]}"

  docker rm -f "$name" >/dev/null
}

run_arm full_contract 6791 wod2sim-replay-full true
run_arm command_only_route 6792 wod2sim-replay-command false

uv run --extra viz python "$ROOT/scripts/generate_alpasim_replay_video.py" \
  --full "$OUTPUT_DIR/full_contract.json" \
  --command "$OUTPUT_DIR/command_only_route.json" \
  --full-telemetry "$OUTPUT_DIR/full_contract-telemetry.jsonl" \
  --command-telemetry "$OUTPUT_DIR/command_only_route-telemetry.jsonl" \
  --frames "$OUTPUT_DIR/frames" \
  --video-output "$ROOT/docs/assets/readme/alpasim-protocol-replay.mp4" \
  --preview-output "$ROOT/docs/assets/readme/alpasim-protocol-replay.gif" \
  --manifest "$OUTPUT_DIR/manifest.json" \
  --docker-image-id "$(docker image inspect "$IMAGE" --format '{{.Id}}')"

echo "Generated camera replay video and README preview under docs/assets/readme"
