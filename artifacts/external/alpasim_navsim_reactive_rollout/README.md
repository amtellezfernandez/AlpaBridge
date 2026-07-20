# Reactive AlpaSim NAVSIM Rollout Evidence

This directory contains the evidence retained from one real AlpaSim
external-driver rollout with the public NAVSIM EgoStatusMLP seed-0 checkpoint.
The learned policy, AlpaSim controller, and AlpaSim physics service formed a
live feedback loop for the full rollout.

This is deliberately not a camera-rendering or policy-quality benchmark. The
checkpoint is camera-blind: its declared input contract is
`velocity_xy+acceleration_xy+discrete_command`. AlpaSim used its
`video_model` renderer boundary, but the external server returned the public
fixture's recorded seed frame on every request. The USDZ also lacked collision
geometry, so WOD2Sim added and declared a flat `z=0` physics surface without
changing the recorded camera, map, or trajectory payloads.

## Result

- AlpaSim: `NVlabs/alpasim@9177bd0bec547d7516cc77d1864e943780ef7e7a`
- WOD2Sim run commit: `aece540bfc916bc9044ed6d4f0512d16093434a7`
- Scene: `clipgt-0b10bce8-61f1-4350-8577-cf3c9493ffc3`
- Rollout: `4956d514-845e-11f1-8b77-537c3b97cc28`, status `pass`
- Learned checkpoint: NAVSIM EgoStatusMLP seed 0 at revision
  `32d89c0ae6e7c13c311f4a034002006c250afab0`
- `Drive`: 197 calls, 197 finite trajectories, 197 below the declared 100 ms
  internal target
- Driver-internal latency: 1.982 ms p50, 3.362 ms p95, 18.143 ms maximum
- AlpaSim-observed `Drive` RPC mean: 3.206 ms over 197 calls
- Runtime: 19.93 simulated seconds in 16.51 active wall-clock seconds;
  18.90 seconds including setup and warmup
- Motion: the renderer's requested ego position advanced from
  `(0.061, -0.001)` m to `(61.683, 0.546)` m

The retained behavior metrics include `wrong_lane=1`; they are not used to
claim learned-policy quality. One scene and one synthetic ground surface
cannot support policy superiority, population generalization, comparative
runtime overhead, human diagnosis time, or cross-simulator transfer.

## Camera Freshness Control

The same scene and static-frame renderer were also connected to the
camera-validating route-following model. Four `Drive` calls completed. On the
fifth camera update, WOD2Sim returned `INVALID_ARGUMENT` because the ego pose
and camera timestamp advanced while the image bytes did not. This is a
negative control for the freshness contract, not a policy comparison; the
failed arm is intentionally truncated and no behavior metrics are compared.

## Files

- `manifest.json`: machine-readable provenance, counts, hashes, limitations,
  and claim boundary
- `driver-telemetry.jsonl`: the 791 events for the successful learned session
- `video-model-telemetry.jsonl`: 198 live trajectory requests received by the
  seed-frame server
- `results-summary.json` and `metrics_results.txt`: AlpaSim aggregate output
- `runtime.log`: complete successful runtime log
- `negative-control-*.jsonl` and `negative-control-runtime.log`: frozen-camera
  control evidence
- `generated-user-config.yaml` and `generated-network-config.yaml`: exact
  expanded AlpaSim configuration
- `camera-map.mp4`: AlpaSim's raw 19.9-second run video; the map moves while the
  camera panel honestly remains the recorded seed frame

[Open the raw camera-and-map run video](camera-map.mp4).

## Reproduction Components

The public USDZ source and learned checkpoint are pinned by immutable revision
and SHA-256 in `manifest.json`; neither is redistributed here. From the
repository root, reconstruct the exact derived fixture with:

```bash
uv run python scripts/prepare_alpasim_public_video_fixture.py
```

Run the video-model endpoint from the pinned AlpaSim environment:

```bash
uv run python scripts/serve_alpasim_seed_video_model.py \
  --port 6790 \
  --telemetry runs/alpasim-navsim-reactive/video-model-telemetry.jsonl
```

Run the WOD2Sim external driver from the runtime image with the pinned
checkpoint mounted at `/checkpoint.ckpt`:

```bash
python -m wod2sim.challenge.e2e_driver \
  --model navsim_ego_status_mlp \
  --checkpoint /checkpoint.ckpt \
  --device cpu
```

Use the retained expanded AlpaSim user and network configs for the runtime,
with managed controller and physics endpoints and external driver
`localhost:6789` and renderer `localhost:6790`. The packaging command is
implemented in `scripts/package_alpasim_navsim_reactive_evidence.py`; it
refuses mismatched session counts, hashes, failure modes, or rollout status.
