# WOD2Sim

<p align="center">
  <a href="https://github.com/amtellezfernandez/WOD2Sim/actions/workflows/ci.yml"><img src="https://github.com/amtellezfernandez/WOD2Sim/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-BSD--3--Clause-blue.svg" alt="BSD-3-Clause license"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-0f766e.svg" alt="Python 3.10+">
</p>

<p align="center">
  <strong>WOD-style trajectory policies as auditable NVIDIA AlpaSim external drivers.</strong><br>
  <a href="arxiv.pdf">Paper</a> |
  <a href="docs/README.md">Documentation</a> |
  <a href="docs/evidence/">Evidence</a> |
  <a href="CITATION.cff">Citation</a>
</p>

<p align="center">
  <img src="docs/assets/readme/alpasim-rollout-screenshot.jpg" alt="Closed-loop AlpaSim rollout with map, metrics, front camera, and route command" width="72%">
</p>

<p align="center"><em>
Figure 1. One <code>spotlight_reflex</code> closed-loop rollout. The top panels show
the ego/actor map and aggregate versus current-timestep metrics; the bottom panel
shows the front camera and current route command. This verifies the integration,
not policy quality.
</em></p>

## Overview

[Waymo Open Motion](https://waymo.com/open/data/motion/) provides logged driving
scenarios; [AlpaSim](https://github.com/NVlabs/alpasim) provides a reactive
closed-loop runtime. WOD2Sim connects their policy interfaces.

- Preserves route geometry and policy-facing scene state at prediction time.
- Registers checkpoint-free, learned, and actor-aware external-driver adapters.
- Hardens model discovery and session handling for batch evaluation.
- Emits manifests, audits, hashes, and benchmark summaries for every rollout.

WOD2Sim is an evaluation adapter, not a new driving policy or dataset converter.

## Install

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
wod2sim-doctor
```

Installation and dry-run planning require neither AlpaSim nor a GPU.

## Reproduce

Create an inspectable plan without launching the simulator:

```bash
wod2sim-reproduce \
  --scene-id example-scene \
  --run-dir /tmp/wod2sim-demo/run \
  --evidence-dir /tmp/wod2sim-demo/evidence \
  --json
```

A plan reports `valid_claim_evidence: false` by design; only an executed and
successfully audited rollout can satisfy the evidence gate.

Live execution requires x86_64 Linux, Docker, an NVIDIA GPU runtime, a local
AlpaSim checkout, and cached scene assets:

```bash
wod2sim-reproduce \
  --execute \
  --alpasim-root /path/to/alpasim \
  --model spotlight_reflex \
  --scene-preset front_camera_10scene_smoke \
  --run-dir runs/spotlight_reflex_10scene \
  --evidence-dir runs/spotlight_reflex_10scene/evidence \
  --json
```

Included adapters are `spotlight_reflex` (checkpoint-free smoke test),
`token_dagger_bc` (checkpoint required), and `direct_actor_planner` (oracle
actor proxy required).

Setup and scale-out details: [integration guide](docs/integration_guide.md) |
[evidence workflow](docs/benchmark_evidence_workflow.md) |
[50/100-scene status](docs/benchmark_regeneration_handoff.md) |
[CLI reference](docs/cli_reference.md).

## Evidence And Results

Each executed run produces a command manifest, run audit, support-bundle report
and hash, plus batch/benchmark summaries. Public summaries remain reviewable
without Docker, AlpaSim, or gated scene assets.

<p align="center">
  <img src="docs/assets/readme/integration-terminal.svg" alt="Audited WOD2Sim run with 199 valid frames, zero sensor failures, and a hashed support bundle" width="88%">
</p>

<p align="center"><em>
Figure 2. Audit summary for the one-scene run in Figure 1. All 199 frames returned
<code>ok</code>, no sensor failures were detected, and the support bundle was
hash-identified. <code>valid_claim_evidence: true</code> validates the evidence
contract; it is not a safety or performance score.
</em></p>

The tracked 10-scene `spotlight_reflex` pilot reports:

| Metric | Result |
| --- | ---: |
| Completed scenes | 10 / 10 |
| Audited frames | 1,990 |
| Sensor-pipeline failures | 0 |
| Any-collision scenes | 5 / 10 |
| At-fault collision scenes | 2 / 10 |
| Wrong-lane / off-road scenes | 3 / 0 |
| Low-progress scenes (`progress < 0.5`) | 7 / 10 |

These values establish runtime and evidence coverage, not a competitive policy
result. The source summary is
[`docs/evidence/closed_loop_spotlight_reflex_10scene_batch.json`](docs/evidence/closed_loop_spotlight_reflex_10scene_batch.json).
The 50- and 100-scene summaries are not claim-ready and remain blocked by the
strict public evidence gate.

<p align="center">
  <img src="docs/assets/readme/evidence-metrics.png" alt="Single-run AlpaSim RPC, timing, service, CPU, and GPU diagnostics" width="88%">
</p>

<p align="center"><em>
Figure 3. Systems diagnostics from the same one-scene rollout. The top row profiles
RPC duration, blocking, and queue depth; the middle row reports rollout/step timing
and service configuration; the bottom row reports host CPU, GPU utilization, and
GPU memory. This plot diagnoses runtime health and is not an aggregate policy metric.
</em></p>

## Verification

```bash
make verify
```

This runs lint, tests and coverage, a fresh-install smoke test, package builds,
and a clean paper rebuild.

## Citation

Use [`CITATION.cff`](CITATION.cff) for software metadata and [`arxiv.pdf`](arxiv.pdf)
for the accompanying paper.

## License And Disclaimer

WOD2Sim is released under the [BSD 3-Clause License](LICENSE). Packaged AlpaSim
overrides retain their [third-party notices](THIRD_PARTY_NOTICES.md).

This is an independent research project and is not affiliated with, endorsed by,
or sponsored by Waymo or NVIDIA. It does not redistribute Waymo datasets,
AlpaSim binaries, gated scene assets, private checkpoints, or rollout bundles;
see the [README media policy](docs/readme_media.md).
