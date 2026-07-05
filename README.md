# WOD2Sim

<p align="center">
  <a href="https://github.com/amtellezfernandez/WOD2Sim/actions/workflows/ci.yml"><img src="https://github.com/amtellezfernandez/WOD2Sim/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-BSD--3--Clause-blue.svg" alt="BSD-3-Clause license"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-0f766e.svg" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/output-manifest%20%2B%20audit%20%2B%20bundle-d97928.svg" alt="Evidence output">
</p>

WOD2Sim is an **unofficial research bridge** for running WOD-style driving
policy adapters inside NVIDIA AlpaSim closed-loop simulation and packaging the
result as auditable evidence.

It connects three surfaces:

| Surface | Role |
| --- | --- |
| [Waymo Open Motion Dataset](https://waymo.com/open/data/motion/) | Logged multi-agent tracks, maps, Scenario protos, tensor examples, and public motion benchmarks. |
| [NVIDIA AlpaSim](https://github.com/NVlabs/alpasim) | Closed-loop AV simulation where policy decisions affect future observations. |
| WOD2Sim | Adapter code, launch CLI, run audit, support bundle, and benchmark summary JSON. |

## What You See

<table>
  <tr>
    <td width="50%">
      <a href="https://waymo.com/intl/jp/open/data/motion/">
        <img src="https://lh3.googleusercontent.com/fUoUF5eid46CnlfsfbRSIVrU0u7oDnn5zzgxXE6ihD2OVNucq_lzIXUWtXlHYEekIx_r6FsMSV3ta6wICLeoYxRv-S56-9d7SuE=e365-s420" alt="Waymo Open Motion Dataset scenario visualization with multi-agent tracks and map geometry" width="100%">
      </a>
      <br>
      <strong>Waymo Motion input.</strong> Scenario-proto style tracks, prediction targets, interacting agents, and vector map geometry. Image is linked from the official Waymo Motion page, not copied into this repository.
    </td>
    <td width="50%">
      <img src="docs/assets/readme/alpasim-rollout-screenshot.jpg" alt="AlpaSim rollout screenshot from a WOD2Sim spotlight_reflex closed-loop run" width="100%">
      <br>
      <strong>AlpaSim rollout screenshot.</strong> Local closed-loop run with map view, per-timestep metrics, front camera, and the WOD2Sim external-driver command overlay.
    </td>
  </tr>
</table>

<p align="center">
  <img src="docs/assets/readme/integration-terminal.svg" alt="WOD2Sim terminal evidence showing completed run, 199 audited frames, zero sensor failures, and valid claim evidence" width="92%">
</p>

<p align="center">
  <img src="docs/assets/readme/evidence-metrics.png" alt="AlpaSim service and runtime metrics from the same WOD2Sim closed-loop run" width="92%">
</p>

This repository is not affiliated with Waymo or NVIDIA. It does not redistribute
Waymo datasets, AlpaSim source/binaries, gated scene assets, private checkpoints,
full rollout videos, or support bundles. The README includes one derived AlpaSim
rollout screenshot and metrics plot from a local run to show what the integration
produces.

## Why This Exists

Waymo Motion is excellent for training and benchmarking motion behavior from
logged trajectories. It is not, by itself, a closed-loop runtime: the world does
not react to a submitted policy.

AlpaSim tests a different failure mode: what happens when the policy's own
actions change the rollout. WOD2Sim provides the bridge from WOD-style policy
signals to AlpaSim external-driver execution, then records the evidence needed to
review the run.

For the detailed dataset and simulator positioning, see
[`docs/waymo_motion_and_alpasim.md`](docs/waymo_motion_and_alpasim.md).

## Paper Positioning

WOD2Sim is best read as a systems, benchmark, and simulator-adapter artifact. It
does not introduce a new autonomous driving policy. The contribution is the
bridge that makes WOD-style trajectory policies executable inside AlpaSim's
closed-loop external-driver runtime, then packages the run as reviewable
evidence.

The current public evidence is strongest for integration and reproducibility:
setup checks, launch materialization, driver logs, audits, support-bundle
hashes, and a recorded one-scene `spotlight_reflex` run. Stronger benchmark
claims should add multi-scene evaluation, baselines, failure taxonomy, and
ablations for route waypoints, model discovery, session lifecycle, and launch
state.

## Quick Start Without Private Assets

Install the package and run the public checks:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
wod2sim-doctor
make test
```

Create a reproduction plan. This does not need AlpaSim or gated assets:

```bash
wod2sim-reproduce \
  --scene-id example-scene \
  --run-dir /tmp/wod2sim-demo/run \
  --evidence-dir /tmp/wod2sim-demo/evidence \
  --json
```

Summarize the planned evidence:

```bash
wod2sim-benchmark-summary \
  --evidence-dir /tmp/wod2sim-demo/evidence \
  --output /tmp/wod2sim-demo/benchmark-summary.json \
  --json
```

The output is useful for reviewing the command path, but it intentionally reports
`valid_claim_evidence: false` until a real AlpaSim run executes.

## Closed-Loop Run With AlpaSim

With a local AlpaSim checkout, Docker/GPU runtime, cached scenes, and any
model-specific artifacts:

```bash
wod2sim-reproduce \
  --execute \
  --alpasim-root /path/to/alpasim \
  --model spotlight_reflex \
  --scene-preset front_camera_10scene_smoke \
  --run-dir runs/benchmark_spotlight_reflex_10scene \
  --evidence-dir runs/benchmark_spotlight_reflex_10scene/evidence \
  --json
```

Then publish a compact benchmark summary instead of raw gated artifacts:

```bash
wod2sim-benchmark-summary \
  --evidence-dir runs/benchmark_spotlight_reflex_10scene/evidence \
  --output runs/wod2sim-benchmark-summary.json \
  --strict \
  --json
```

A local one-scene `spotlight_reflex` run is summarized in
[`docs/evidence/closed_loop_spotlight_reflex_one_scene.json`](docs/evidence/closed_loop_spotlight_reflex_one_scene.json):
199 audited frames and 0 sensor failures. The raw rollout media and support
bundle are not tracked because they may contain AlpaSim or gated-scene-derived
content.

## Evidence Contract

A closed-loop claim should include:

| Artifact | Purpose |
| --- | --- |
| `closed-loop-reproduction-manifest.json` | Exact commands, model, scenes, provenance, and claim boundary. |
| `run-audit.json` | Driver-log summary, frame counts, result counts, and sensor freshness status. |
| `support-bundle-report.json` | Report for the packaged run logs, configs, and normalized audit export. |
| `support-bundle.tar.gz` hash | Local artifact integrity without redistributing gated files by default. |
| `wod2sim-benchmark-summary.json` | Multi-run aggregate with strict evidence validation. |

Dry-run plans are valid review artifacts. They are not closed-loop evidence.

## Waymo Motion Dataset Context

WOD2Sim is designed around the Waymo Open Motion Dataset format and benchmark
framing:

| Feature | Waymo Motion |
| --- | --- |
| Storage | Sharded TFRecord files containing protocol buffer data. |
| Splits | 70% training, 15% validation, 15% testing. |
| Scale | 103,354 segments, each with 20 seconds of object tracks at 10 Hz plus map data. |
| Model windows | 9 seconds: 1 second history and 8 seconds future. |
| Scenario proto | Object tracks, dynamic map states, static map features, SDC track index, objects of interest, prediction targets, and current time index. |
| Tensor format | `tf.Example` protos for model training pipelines. |
| Benchmarks | Interaction Prediction, Sim Agents, and Scenario Generation among the WOD challenge tracks. |

The README uses an official Waymo-hosted Scenario-proto visualization from the
Motion page as the dataset image. This repository links to that source instead
of copying Waymo website assets into git.

## Public Model Surface

| Model | Use |
| --- | --- |
| `spotlight_reflex` | Checkpoint-free smoke-test adapter. |
| `token_dagger_bc` | Learned policy adapter; requires `--checkpoint /path/to/token_dagger_bc.pt`. |
| `direct_actor_planner` | Planner adapter; requires `--oracle-actor-proxy /path/to/oracle.json`. |

Examples:

```bash
wod2sim-launch --mode print --model spotlight_reflex
wod2sim-launch --mode print --model token_dagger_bc --checkpoint /path/to/token_dagger_bc.pt
wod2sim-build-oracle-proxy --run-dir /path/to/run --output /path/to/oracle.json
wod2sim-launch --mode print --model direct_actor_planner --oracle-actor-proxy /path/to/oracle.json
```

## Main Commands

| Command | Purpose |
| --- | --- |
| `wod2sim-doctor` | Validate package install and optional AlpaSim environment. |
| `wod2sim-setup` | Wire WOD2Sim into a local AlpaSim checkout. |
| `wod2sim-ready` | Validate AlpaSim runtime and scene readiness. |
| `wod2sim-launch` | Print or launch AlpaSim external-driver runs. |
| `wod2sim-reproduce` | Plan or execute the full closed-loop evidence workflow. |
| `wod2sim-audit-run` | Summarize executed run logs and sensor freshness. |
| `wod2sim-support-bundle` | Package key run logs, configs, and audit output. |
| `wod2sim-benchmark-summary` | Aggregate evidence directories into one benchmark JSON. |

## Media Policy

Public README media should come from official external links,
redistribution-approved dataset frames, AlpaSim rollout screenshots or clips,
integration screenshots, or evidence plots. Local candidates under `runs/` and
`workspace/` are intentionally ignored because they may contain gated or
third-party content. The tracked AlpaSim screenshot and metrics plot are derived
from the recorded one-scene `spotlight_reflex` run.

See [`docs/readme_media.md`](docs/readme_media.md) before adding images or video.

## Repository Layout

| Path | Contents |
| --- | --- |
| `src/wod2sim/` | Python package. |
| `src/wod2sim/simulator/` | AlpaSim adapters and simulator-facing logic. |
| `src/wod2sim/cli/commands/` | Runtime and evidence CLI implementations. |
| `scripts/` | Top-level wrappers for public workflows. |
| `third_party/alpasim_overrides/` | Tracked AlpaSim override layer and patches. |
| `docs/` | Integration, evidence, media, and Waymo/AlpaSim positioning docs. |
| `paper/` | LaTeX paper source. |
| `tests/` | Contract and release-surface tests. |

## Development

Run the standard checks:

```bash
make test
make verify
```

Build the paper:

```bash
make paper
```

Clean generated local artifacts:

```bash
make clean
```

## Citation

If you use this repository in academic work, cite the software metadata in
[`CITATION.cff`](CITATION.cff) and the paper under [`paper/`](paper).

## License

The repository is distributed under the BSD 3-Clause License. Some packaged
AlpaSim override files carry separate third-party notices; see
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
