# Reproducing Current WOD2Sim Contract-Validation Matrix (CVM) Artifacts

Current status: buildable WOD2Sim paper package with a completed
dependency-light public core, completed semantic closed-loop ablation rows,
secondary public synthetic lifecycle/fault conformance diagnostics, and
explicit optional gated direct-actor blockers. A separate public protocol replay
records current-schema client-to-service gRPC timing and contract diagnostics.

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

The current aggregate supports a completed dependency-light public core,
completed full-contract integration checks, and bounded semantic
route-boundary confound evidence. It does not support a complete public
benchmark. Blocked rows remain optional gated extension denominator/context
only. The aggregate does not support direct-actor temporal ablation,
learned-policy quality, visual-policy behavior, scenario-category coverage,
restricted scene redistribution, human diagnosis time, or empirical
generalization to another integration framework.

Failure attribution is explicit in `artifacts/cvm/results/summary.json` under
`failure_attribution`. A behavior row is policy-attributable only after route,
sensor, lifecycle, deployment, and evidence gates pass. Contract-invalid rows,
blocked rows, planned rows, and synthetic diagnostics must be reported as
integration/precondition/evidence states, not policy failures.

Every public run manifest also carries `scene` metadata and top-level
`scenario_category`. Current local closed-loop scenes are recorded as
`available_front_camera_26_02_unclassified`; this records the coverage
limitation rather than claiming authoritative scenario categories.
