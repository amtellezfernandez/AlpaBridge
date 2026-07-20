# AlpaSim Protocol Replay Evidence

This directory records a paired, current-schema client-to-service replay
against two live WOD2Sim gRPC driver processes. It is transport, output-validity,
and automatic contract-diagnostic evidence. It is not a reactive closed-loop
simulation, a policy benchmark, a human diagnosis study, or a comparison with
another integration framework.

## Source

- Upstream project: NVIDIA AlpaSim.
- Upstream commit: `049f70fbfe8207e1efd4831a6c3e78a38703d473`.
- Fixture: `src/runtime/tests/data/integration/rollout.asl`.
- Fixture SHA-256:
  `237d6b55f4da5b0610f1b8b1e940f52d9efdc9e39c8ca2b35c5b5285ebefdc1f`.
- Camera shown: `camera_front_wide_120fov`.
- License: Apache License 2.0; see
  [`LICENSES/THIRD_PARTY_NOTICES.md`](../../../LICENSES/THIRD_PARTY_NOTICES.md).

The runner downloads the fixture from the exact commit and refuses to continue
if its hash differs. Extracted JPEG frames remain untracked under `frames/`;
the committed MP4 and GIF contain the executed replay with a WOD2Sim diagnostic
overlay.

## Method

The runner builds the current challenge-driver image and starts two services in
this fixed order:

1. `full_contract`
2. `command_only_route`

It sends the same recorded session, route, egomotion, camera, and `Drive`
messages to both services over host-loopback gRPC. The client associates each
`Drive` call with the latest recorded wide-camera frame and measures the complete
client RPC with `time.perf_counter_ns`. The current run used an Intel Core Ultra
9 275HX host under WSL2 and Docker image
`sha256:2cdabfeb7254f3de88dd0c422ee7965e584b461c59689898044155afe31ecd7b`.
The manifest records the remaining environment and source hashes.

## Results

| Arm | Finite outputs | Drive latency median | Drive latency p95 | Contract diagnostics |
| --- | ---: | ---: | ---: | --- |
| `full_contract` | 60/60 | 1.786 ms | 2.191 ms | none |
| `command_only_route` | 60/60 | 1.835 ms | 2.338 ms | `semantic.command_only` |

All 60 calls in each arm are below the configured 100 ms target. The two arms
were run once and sequentially, so their latency difference is descriptive and
does not estimate format overhead.

The ASL sequence is recorded and non-reactive: service outputs cannot alter
later camera or ego-state messages. Therefore these measurements include gRPC
serialization, host-loopback transport, service dispatch, adapter execution,
and response serialization, but exclude simulator stepping, rendering, vehicle
dynamics feedback, and human investigation.

## Files

- `manifest.json`: hashes, environment, scope, diagnostics, and summarized
  measurements.
- `full_contract.json`: per-call client measurements and trajectories.
- `command_only_route.json`: paired reduced-format measurements and
  trajectories.
- `*-telemetry.jsonl`: current-schema service telemetry used by the contract
  audit.
- `docs/assets/readme/alpasim-protocol-replay.mp4`: canonical 8-second H.264
  video.
- `docs/assets/readme/alpasim-protocol-replay.gif`: same-frame README preview.

Reproduce the complete run with:

```bash
ALPASIM_ROOT=/path/to/alpasim ./scripts/run_alpasim_replay_demo.sh
```
