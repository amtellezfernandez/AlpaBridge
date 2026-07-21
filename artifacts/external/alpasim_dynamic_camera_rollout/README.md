# Dynamic-Camera AlpaSim Rollout Evidence

This directory contains the evidence retained from one real AlpaSim
external-driver rollout with a private `token_dagger_bc` behavior-cloned
checkpoint. Unlike the [reactive NAVSIM
rollout](../alpasim_navsim_reactive_rollout/), AlpaSim served this run from
its live `sensorsim` renderer, not the repeated-frame `video_model` fixture:
the camera panel in the retained video genuinely changes frame to frame.

## Why This Exists

The NAVSIM reactive rollout is fully public and reproducible, but its
checkpoint is camera-blind, so its camera panel honestly repeats one
recorded frame. That is accurate evidence, but it reads as a frozen or
broken preview to a viewer who has not read the caveat. This rollout
demonstrates the same external-driver lifecycle with an actually moving
camera, at the cost of using a checkpoint this repository does not
distribute.

## Result

- AlpaBridge run commit: `e39357d7cdeda9118ea3aa4938b026a0b2781068`
- Scene: `clipgt-81b0e06d-96e6-4832-99c1-a4084b54ca97` (part of this
  repository's `front_camera_10scene_smoke` / `front_camera_30scene_merged`
  gated scene presets)
- Rollout: `9865c414-581a-11f1-8736-a9806c3c5917`, status `pass`
- Model: `token_dagger_bc`, a private behavior-cloned checkpoint, **not
  redistributed in this repository**
- Renderer: AlpaSim `sensorsim` (live), warmup `92.211` s
- `100` driver inference batches over `200` simulation steps
- Runtime: `19.90` simulated seconds in `17.66` s session wall-clock time
  (`135.40` s including setup and sensorsim warmup)
- `dist_traveled_m`: `27.57`; `collision_any`, `offroad`,
  `safety_monitor_triggered`: all `0.00`

The retained behavior metrics (including `progress=0.16` and
`plan_deviation=0.41`) are not used to claim policy quality. One scene and
one checkpoint cannot support population generalization, comparative
runtime overhead, or cross-simulator transfer.

## What This Evidence Is Missing, Compared To The NAVSIM Rollout

This run was captured with less granular telemetry than the [reactive
NAVSIM rollout](../alpasim_navsim_reactive_rollout/):

- No per-`Drive`-call JSONL telemetry was retained, only the aggregate
  `driver.stdout.log`, AlpaSim's `runtime.log`, and `metrics_results.txt`.
  There is no equivalent of `driver-telemetry.jsonl`'s per-call latency
  breakdown here.
- The AlpaSim commit used for this run was not captured at run time and is
  recorded as `null` in `manifest.json` rather than guessed.
- `run_metadata.yaml`, `source-launch-metadata.json`, and
  `external-driver-config.yaml` originally contained absolute filesystem
  paths and a username from a separate, private repository checkout. Those
  fields have been redacted in place; the redaction list and reason are
  recorded in `manifest.json`'s `redactions` block.

## Files

- `manifest.json`: machine-readable provenance, counts, hashes, redactions,
  and claim boundary
- `driver.stdout.log`: aggregate driver-side log for the session
  (session start/close, inference batch count)
- `generated-user-config.yaml` and `generated-network-config.yaml`: the
  exact expanded AlpaSim configuration, including the enabled `sensorsim`
  endpoint
- `external-driver-config.yaml`: the driver config actually served, with
  the private checkpoint path redacted
- `metrics_results.txt`: AlpaSim's aggregate behavior metrics for the
  rollout
- `runtime.log`: complete AlpaSim runtime log, including the `sensorsim`
  warmup and session lifecycle
- `camera-map.mp4`: AlpaSim's raw run video, map output stacked over the
  live camera render
- `camera.mp4`: a camera-only crop of the same rollout

[Open the raw camera-and-map run video](camera-map.mp4). |
[Open the camera-only crop](camera.mp4). |
[Full-frame standalone preview](../../../docs/assets/readme/alpasim-dynamic-camera-full.gif) |
[Camera-only standalone preview](../../../docs/assets/readme/alpasim-dynamic-camera.gif) |
[Camera side-by-side comparison, superseded by the hero below](../../../docs/assets/readme/alpasim-camera-comparison.gif) |
[Motion-shadow comparison](../../../docs/assets/readme/alpasim-motion-shadow.gif) |
[README hero (top half: this rollout's own map panel + motion-shadow camera composite)](../../../docs/assets/readme/alpasim-demo-two-rollouts.gif).

## Reproduction

The scene, AlpaBridge commit, and AlpaSim configuration are recorded above and
in `manifest.json`. The checkpoint itself is private and not distributed
with this repository, so this exact rollout cannot be reproduced from public
inputs alone. To reproduce the lifecycle shape with a checkpoint you supply,
follow [the reproduction guide](../../../docs/reproduction.md) with the
`token_dagger_bc` preset and your own local checkpoint path.
