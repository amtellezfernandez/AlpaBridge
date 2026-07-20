# AlpaSim Protocol Replay Evidence

This directory records a four-arm, current-schema client-to-service replay
against live WOD2Sim gRPC driver processes. It crosses two policy signatures
with two route representations:

- route following requires waypoint geometry;
- NAVSIM EgoStatusMLP consumes ego velocity, acceleration, and a discrete
  command, but not route geometry.

The replay provides transport-inclusive service timing, output validity,
policy-specific contract diagnostics, and paired trajectory evidence. It is not
a reactive closed-loop simulation, policy-quality benchmark, human-diagnosis
study, format-overhead experiment, or cross-framework comparison.

## Recorded Source

- Upstream project: NVIDIA AlpaSim.
- Upstream commit: `049f70fbfe8207e1efd4831a6c3e78a38703d473`.
- Fixture: `src/runtime/tests/data/integration/rollout.asl`.
- Fixture SHA-256:
  `237d6b55f4da5b0610f1b8b1e940f52d9efdc9e39c8ca2b35c5b5285ebefdc1f`.
- Camera shown: `camera_front_wide_120fov`.
- License: Apache License 2.0; see
  [`LICENSES/THIRD_PARTY_NOTICES.md`](../../../LICENSES/THIRD_PARTY_NOTICES.md).

The runner downloads the fixture from the exact commit and rejects a hash
mismatch. Extracted JPEG frames remain untracked under `frames/`. The committed
MP4 and GIF use the same recorded camera frames on the left and right. The
camera images contain no overlay; causal labels and trajectory plots are placed
outside them.

## Learned Checkpoint

The learned arms use NAVSIM's official `ego_status_mlp_seed_0` baseline:

- repository: `autonomousvision/navsim_baselines`;
- checkpoint revision:
  `32d89c0ae6e7c13c311f4a034002006c250afab0`;
- checkpoint SHA-256:
  `87d75b0f43d077ac3531370d7cccac98656d4e9b5ce5fa6618e28b7358b3a86b`;
- NAVSIM v1.1 source commit:
  `0811876c274e8b058ab2be9b3dcd4d37bd23f177`;
- license: Apache License 2.0.

The runner downloads and verifies the checkpoint; WOD2Sim does not redistribute
it. The adapter reproduces the published 8-input, three-hidden-layer MLP and its
eight-pose, 4-second, 2 Hz output. This is a learned blind baseline, not a visual
or multimodal policy. It is used as a policy-signature negative control, not as
evidence that route loss changes every policy.

## Method

The runner starts four services in this fixed order:

1. `full_contract` using route following;
2. `command_only_route` using route following;
3. `navsim_ego_status_mlp_full_contract`;
4. `navsim_ego_status_mlp_command_only_route`.

Every service receives the same 60 recorded session, route, egomotion, camera,
and `Drive` messages over host-loopback gRPC. The full mode retains all 20 route
points; the reduced mode retains only the derived turn command. The audit
requires route geometry only when the policy declares it. Calls are paired by
index, timestamps, and raw route, and endpoint differences are measured in the
local ego frame.

The client times the complete RPC with `time.perf_counter_ns`. The current run
used an Intel Core Ultra 9 275HX host under WSL2. The dependency-light image is
`sha256:4fbbcb9406cb65796a28a8532f2126fdc224cde4feaed9a546d5e818fdaa5586`;
the learned runtime image is
`sha256:7ba4dbee3391aeb473aff739350e57e01f3019b84f7177e0e7e2503bce8e8732`.
The manifest records the remaining environment, source, artifact, and media
hashes.

## Results

| Arm | Finite/moving outputs | Drive latency median | Drive latency p95 | Contract diagnostics |
| --- | ---: | ---: | ---: | --- |
| `full_contract` | 60/60 | 3.769 ms | 4.833 ms | none |
| `command_only_route` | 60/60 | 3.104 ms | 3.958 ms | `semantic.command_only` |
| `navsim_ego_status_mlp_full_contract` | 60/60 | 4.715 ms | 5.945 ms | none |
| `navsim_ego_status_mlp_command_only_route` | 60/60 | 4.943 ms | 6.963 ms | none |

Every arm returns 60/60 finite trajectories, advances more than 1 m, and meets
the configured 100 ms target. Removing route geometry changes the
route-following endpoint by more than 0.1 m on 56/60 calls and by more than 1 m
on 22/60 calls; mean and maximum separation are 0.708 m and 1.506 m.

All 60 NAVSIM full/reduced trajectory pairs are exactly equal. This is the
expected negative-control result because the published EgoStatusMLP input
signature contains no route geometry. Reporting a semantic fault for that arm
would itself be an audit false positive.

The four arms were run once and sequentially in two runtime images. Latency
differences are descriptive and do not estimate format or policy overhead. The
ASL sequence is recorded and non-reactive: service outputs cannot alter later
camera or ego-state messages. The measurements include gRPC serialization,
host-loopback transport, service dispatch, adapter execution, and response
serialization, but exclude simulator stepping, rendering, vehicle-dynamics
feedback, and human investigation.

## Files

- `manifest.json`: hashes, environment, policy provenance, scope, diagnostics,
  and summarized measurements.
- `full_contract.json` and `command_only_route.json`: route-following client
  measurements and trajectories.
- `navsim_ego_status_mlp_full_contract.json` and
  `navsim_ego_status_mlp_command_only_route.json`: learned negative-control
  measurements and trajectories.
- `*-telemetry.jsonl`: schema-v3 service telemetry used by the contract audit.
- `docs/assets/readme/alpasim-protocol-replay.mp4`: canonical 4.5-second H.264
  camera comparison.
- `docs/assets/readme/alpasim-protocol-replay.gif`: same-frame README preview.

Reproduce the complete run with:

```bash
ALPASIM_ROOT=/path/to/alpasim ./scripts/run_alpasim_replay_demo.sh
```
