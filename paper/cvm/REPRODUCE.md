# Reproducing Current WOD2Sim Contract-Validation Matrix (CVM) Artifacts

Current status: buildable WOD2Sim paper package with a completed
dependency-light public core, completed semantic closed-loop ablation rows,
secondary public synthetic lifecycle/fault conformance diagnostics, and
explicit optional gated direct-actor blockers. A separate public protocol replay
records current-schema client-to-service gRPC timing and contract diagnostics;
one public-fixture learned rollout records live external-driver/controller/
physics feedback. The primary attribution experiment uses the pinned Waymax
route fixture in a policy-by-route negative-control design.

## Quality Gates

```bash
make cvm-check PYTHON='uv run python'
```

This runs lint, dependency-light conformance tests, and paper validation.

## Matrix Expansion And Execution

Record core launch plans without launching:

```bash
uv run python scripts/run_cvm_matrix.py \
  --config configs/cvm/core.yaml \
  --output artifacts/cvm/results/core \
  --resume
```

Execute supported local closed-loop rows. In the current public release this
preserves the completed `constant_velocity` and `route_following` public-core
rows and records direct-actor rows as optional gated blockers unless a
scene-matched oracle proxy is configured:

```bash
uv run python scripts/run_cvm_matrix.py \
  --config configs/cvm/core.yaml \
  --output artifacts/cvm/results/core \
  --resume \
  --execute
```

Execute the completed semantic route-boundary CVM:

```bash
uv run python scripts/run_cvm_matrix.py \
  --config configs/cvm/semantic_ablation.yaml \
  --output artifacts/cvm/results/semantic_ablation \
  --resume \
  --execute
```

The command-only route arm is explicit and non-default:
`WOD2SIM_ROUTE_CONTRACT_MODE=command_only_route`. AlpaSim video rendering is
disabled in CVM configs with `eval.video.render_video=false`.

The `seed` column is a configured execution identifier. It is recorded in
manifests and run IDs, but it is not yet forwarded as a deterministic AlpaSim
runtime seed override. Runtime seed metadata is logged when the patched
external-driver input exposes it.

## Secondary Public Synthetic Diagnostics

```bash
make cvm-synthetic PYTHON='uv run python'
```

These rows are service-harness diagnostics only; they are not closed-loop scene
rollouts, are not effectiveness metrics for simulator-backed integration, and
remain `claim_valid=false`.

## Waymax/WOMD Attribution Study

```bash
./scripts/run_waymax_contract_study.sh
```

The runner clones Waymax at
`a64dfec9be8576b60d9cecc94f406d9812d4a7d0`, verifies the bundled WOMD route
TFRecord hash, installs the pinned checkout into an isolated environment, and
executes four 50-step arms for every comparison-eligible scenario. The route
following arms use the same pure-pursuit controller with either original
`sdc_paths.on_route` geometry or an intervention-defined `KEEP_HEADING`
geometric proxy. Constant velocity traverses the same route conversion but
does not consume it.

The retained artifact under `artifacts/external/waymax_contract_study` includes
scenario rows, aggregate summary, implementation hashes, and a manifest. Of 20
TFExamples, 19 are eligible. Route-following endpoint divergence is 1.017 m
median; constant velocity is invariant in 19/19; the audit rejects only the
19 route-following proxy arms. The upstream data is not redistributed and the
study outputs remain governed by the Waymax License Agreement for
Non-Commercial Use.

## Paired AlpaSim Protocol Replay

Run the same official recorded AlpaSim integration protocol through four live
services: route following and NAVSIM EgoStatusMLP, each under route-retaining
and command-only service modes:

```bash
ALPASIM_ROOT=/path/to/alpasim ./scripts/run_alpasim_replay_demo.sh
```

The runner hash-checks the upstream ASL fixture, downloads and hash-checks
NAVSIM's official `ego_status_mlp_seed_0` checkpoint, rebuilds the
challenge-driver image, executes all four arms, and regenerates the JSON/JSONL
evidence, H.264 video, and README preview. The checkpoint is not redistributed.
The aggregate rejects changed evidence, source, or media hashes and re-runs the
trace diagnostics.

The replay records 60 `Drive` calls per arm. Every arm returns 60/60 finite,
nonstationary trajectories and meets the 100 ms target. Removing geometry
isolates `semantic.command_only` for route following and changes 56/60
endpoints. It correctly produces no fault and no output change for the NAVSIM
model because route geometry is outside that model's published input
signature. Route-following full/reduced median/p95 latency is 3.769/4.833 ms
and 3.104/3.958 ms; NAVSIM full/reduced is 4.715/5.945 ms and
4.943/6.963 ms.

This recording is non-reactive: service outputs do not alter later camera or
ego-state messages. The values therefore include loopback gRPC and service
execution but exclude simulator stepping and closed-loop feedback. One ordered
execution per arm does not support a format-overhead claim or human
time-to-diagnosis result.

## Reactive AlpaSim NAVSIM Rollout

The retained learned run is under
`artifacts/external/alpasim_navsim_reactive_rollout`. Reconstruct the exact
public fixture derivative from its pinned upstream source:

```bash
uv run python scripts/prepare_alpasim_public_video_fixture.py
```

The script verifies upstream SHA-256
`0ee95b5bc3a69693cd5a3da3a7d430b673f15371f6844f641866302b5deab2f6`,
adds only the declared flat `mesh.ply`, `mesh_ground.ply`, and derivation record,
and verifies derived SHA-256
`069fd063a64c82112ec971b585b7eb08d09f9233a4f2ac5e816e19af7185d70d`.
Run `scripts/serve_alpasim_seed_video_model.py` from the pinned AlpaSim
environment on port 6790 and the WOD2Sim challenge driver with model
`navsim_ego_status_mlp` and the checkpoint pinned in the manifest. The retained
expanded user and network configs use external driver `localhost:6789`,
external renderer `localhost:6790`, and managed controller and physics
services.

The run completes 1/1 rollout, 197/197 finite outputs, and 19.93 simulated
seconds. The artifact contains the raw camera-and-map MP4, both service
telemetry streams, AlpaSim summary and runtime logs, the exact configs, and a
same-scene frozen-camera negative control. Repackage only with
`scripts/package_alpasim_navsim_reactive_evidence.py`; it rejects count,
provenance, hash, and diagnostic drift.

The learned policy is camera-blind. The video-model endpoint repeats the
recorded public seed frame, and the declared ground is synthetic and flat.
Accordingly, this supports live policy/controller/physics lifecycle and timing
for the exact configuration, not visual-policy behavior, policy quality,
comparative overhead, human diagnosis time, or cross-simulator transfer.

## Aggregate, Figures, And Paper

```bash
make cvm-aggregate PYTHON='uv run python'
make paper-verify PYTHON='uv run python'
```

The output PDF is the repository-root `wod2sim.pdf`. `paper-verify` rebuilds
that PDF and runs the submission validator. The `paper/cvm/` directory contains
the source and generated TeX inputs, not a second tracked paper PDF.
The validator also checks `paper/cvm/metadata.json`; update that file whenever
the title, author block, PDF subject, or abstract text intentionally changes.

## Current Claim Boundary

- Configured rows: 148.
- Public-core rows completed: 30/30.
- Attempted rows: 115.
- Completed rows: 115.
- Closed-loop completed rows: 60.
- Full-contract rows audit-valid: 42/45.
- Comparison-eligible semantic pairs: 14/15.
- Command-only rows rejected as non-claim-valid: 15/15.
- Status-only baseline accepted rows: 15/15.
- Planned rows: 0.
- Blocked rows: 33.
- Claim-valid benchmark matrix: 0.
- External interface conformance: 1/1 rollout, 197 driver RPCs, 396 image
  events, and 197/197 latency-target hits.
- Current-schema protocol replay: four arms with 60/60 finite, nonstationary
  `Drive` outputs and 60/60 latency-target hits each; route loss produces one
  `semantic.command_only` diagnostic and 56/60 route-following endpoint
  changes, while the NAVSIM negative control has no diagnostic and 60/60 exact
  output matches.
- Reactive NAVSIM rollout: 1/1 pass, 197/197 finite outputs, 198 camera events,
  198 renderer requests, 19.93 simulated seconds, and a route-following
  frozen-camera control rejected after four completed calls.
- Waymax/WOMD factorial: 20 fixture scenarios, 19 comparison-eligible,
  3,800 closed-loop steps, 1.017 m median route-following endpoint divergence,
  19/19 exact constant-velocity invariance, and 19/19 correct audit decisions
  in each factorial cell.

The current aggregate supports a completed dependency-light public core,
completed full-contract integration checks, and bounded semantic
route-boundary confound evidence. It does not support a complete public
benchmark. Blocked rows remain optional gated extension denominator/context
only. The aggregate does not support direct-actor temporal ablation,
learned-policy quality, visual-policy behavior, scenario-category coverage,
restricted scene redistribution, human diagnosis time, or empirical
generalization of all contracts to another integration framework. The Waymax
study supports cross-runtime applicability of the route semantic rule only. It
reports exact runtime for the single reactive configuration, not comparative
runtime overhead.

Failure attribution is explicit in `artifacts/cvm/results/summary.json` under
`failure_attribution`. A behavior row is policy-attributable only after route,
sensor, lifecycle, deployment, and evidence gates pass. Contract-invalid rows,
blocked rows, planned rows, and synthetic diagnostics must be reported as
integration/precondition/evidence states, not policy failures.

Every public run manifest also carries `scene` metadata and top-level
`scenario_category`. Current local closed-loop scenes are recorded as
`available_front_camera_26_02_unclassified`; this records the coverage
limitation rather than claiming authoritative scenario categories.
