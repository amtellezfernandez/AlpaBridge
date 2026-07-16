# WOD2Sim

<p align="center">
  <a href="https://github.com/amtellezfernandez/WOD2Sim/actions/workflows/ci.yml"><img src="https://github.com/amtellezfernandez/WOD2Sim/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-BSD--3--Clause-blue.svg" alt="BSD-3-Clause license"></a>
  <img src="https://img.shields.io/badge/python-3.10%2B-0f766e.svg" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/output-manifest%20%2B%20audit%20%2B%20bundle-d97928.svg" alt="Evidence output">
</p>

**Run WOD-style driving policies inside NVIDIA AlpaSim closed-loop simulation —
and get auditable evidence out.**

The Waymo Open Motion Dataset gives you logged trajectories. AlpaSim gives you
a world that reacts to your policy's decisions. WOD2Sim is the unofficial
research bridge between them: policy adapters, a launch CLI, run audits, and a
reproducible evidence packet for every rollout.

<table>
  <tr>
    <td width="50%">
      <a href="https://waymo.com/intl/jp/open/data/motion/">
        <img src="https://lh3.googleusercontent.com/fUoUF5eid46CnlfsfbRSIVrU0u7oDnn5zzgxXE6ihD2OVNucq_lzIXUWtXlHYEekIx_r6FsMSV3ta6wICLeoYxRv-S56-9d7SuE=e365-s420" alt="Waymo Open Motion Dataset scenario visualization with multi-agent tracks and map geometry" width="100%">
      </a>
      <br>
      <strong>Input: Waymo Motion.</strong> Scenario-proto tracks, interacting agents, and vector map geometry. Image linked from the official Waymo Motion page, not copied into this repository.
    </td>
    <td width="50%">
      <img src="docs/assets/readme/alpasim-rollout-screenshot.jpg" alt="AlpaSim rollout screenshot from a WOD2Sim spotlight_reflex closed-loop run" width="100%">
      <br>
      <strong>Output: AlpaSim rollout.</strong> Local closed-loop run with map view, per-timestep metrics, front camera, and the WOD2Sim external-driver command overlay.
    </td>
  </tr>
</table>

<p align="center">
  <img src="docs/assets/readme/integration-terminal.svg" alt="WOD2Sim terminal evidence showing completed run, 199 audited frames, zero sensor failures, and valid claim evidence" width="92%">
</p>

<p align="center">
  <img src="docs/assets/readme/evidence-metrics.png" alt="AlpaSim service and runtime metrics from the same WOD2Sim closed-loop run" width="92%">
</p>

## Why

Waymo Motion is excellent for training and benchmarking motion behavior from
logged trajectories. It is not, by itself, a closed-loop runtime: the world
does not react to a submitted policy. AlpaSim tests the failure mode logged
data cannot — what happens when the policy's own actions change the rollout.

WOD2Sim connects three surfaces:

| Surface | Role |
| --- | --- |
| [Waymo Open Motion Dataset](https://waymo.com/open/data/motion/) | Logged multi-agent tracks, maps, Scenario protos, and public motion benchmarks. |
| [NVIDIA AlpaSim](https://github.com/NVlabs/alpasim) | Closed-loop AV simulation where policy decisions affect future observations. |
| WOD2Sim | Adapter code, launch CLI, run audit, support bundle, and benchmark summary JSON. |

WOD2Sim does not introduce a new driving policy. Its contribution is systems
and evaluation: making WOD-style trajectory policies executable inside
AlpaSim's external-driver runtime, then packaging each run as reviewable
evidence. For dataset and simulator positioning — including how this compares
to Waymax — see
[`docs/waymo_motion_and_alpasim.md`](docs/waymo_motion_and_alpasim.md).

> This repository is not affiliated with Waymo or NVIDIA. It does not
> redistribute Waymo datasets, AlpaSim source/binaries, gated scene assets,
> private checkpoints, rollout videos, or support bundles. README media policy:
> [`docs/readme_media.md`](docs/readme_media.md).

## Quick Start

No AlpaSim, GPU, or gated assets required:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
wod2sim-doctor
```

Create and summarize a reproduction plan:

```bash
wod2sim-reproduce \
  --scene-id example-scene \
  --run-dir /tmp/wod2sim-demo/run \
  --evidence-dir /tmp/wod2sim-demo/evidence \
  --json

wod2sim-benchmark-summary \
  --evidence-dir /tmp/wod2sim-demo/evidence \
  --output /tmp/wod2sim-demo/benchmark-summary.json \
  --json
```

The output shows the full command path and evidence layout. It intentionally
reports `valid_claim_evidence: false` until a real AlpaSim run executes — dry
plans are review artifacts, not closed-loop evidence.

## Closed-Loop Run With AlpaSim

Live rollouts need an x86_64 Linux host with Docker, an NVIDIA GPU runtime, a
local AlpaSim checkout, and cached scene assets. Then one command plans,
executes, audits, and packages the run:

```bash
wod2sim-reproduce \
  --execute \
  --alpasim-root /path/to/alpasim \
  --model spotlight_reflex \
  --scene-preset front_camera_10scene_smoke \
  --run-dir runs/benchmark_spotlight_reflex_10scene_fresh \
  --evidence-dir runs/benchmark_spotlight_reflex_10scene_fresh/evidence \
  --json
```

For multi-scene pilots, `wod2sim-batch` runs scenes as independent statistical
units with timeouts and retries. Setup details, cache building for the larger
26.02 presets, shard/merge/promotion workflows, and host compatibility are in
the docs index and the detailed workflow pages:

- [`docs/README.md`](docs/README.md) — documentation map.
- [`docs/integration_guide.md`](docs/integration_guide.md) — day-0 setup and first run.
- [`docs/closed_loop_reproduction.md`](docs/closed_loop_reproduction.md) — the reproduction workflow and claim boundary.
- [`docs/benchmark_evidence_workflow.md`](docs/benchmark_evidence_workflow.md) — batch runs, caches, audits, and claim gating.

## Evidence Contract

Every closed-loop claim ships as a compact, hash-verified packet:

| Artifact | Purpose |
| --- | --- |
| `closed-loop-reproduction-manifest.json` | Exact commands, model, scenes, provenance, and claim boundary. |
| `run-audit.json` | Driver-log summary, frame counts, result counts, and sensor freshness status. |
| `support-bundle-report.json` | Report for the packaged run logs, configs, and normalized audit export. |
| `support-bundle.tar.gz` hash | Local artifact integrity without redistributing gated files. |
| `wod2sim-benchmark-summary.json` | Multi-run aggregate with strict evidence validation. |
| `wod2sim-batch-summary.json` | Multi-scene batch metrics, failure taxonomy, and local artifact hashes without raw media. |

Open-repo readers can review every tracked summary in
[`docs/evidence/`](docs/evidence/) without AlpaSim, Docker, or gated assets.

## Results So Far

A local 10-scene `spotlight_reflex` pilot
([`docs/evidence/closed_loop_spotlight_reflex_10scene_batch.json`](docs/evidence/closed_loop_spotlight_reflex_10scene_batch.json)):

| Metric | Value |
| --- | --- |
| Scenes completed | 10/10 |
| Audited frames | 1,990 |
| Sensor-pipeline failures | 0 |
| Collision scenes (2 at-fault) | 5 |
| Wrong-lane / offroad scenes | 3 / 0 |
| Low-progress scenes | 7 |

These are policy/runtime evidence metrics, not a claim that the bundled smoke
adapter is a strong driving policy — `spotlight_reflex` exists to prove the
bridge, not to win the benchmark. The 50- and 100-scene stages are planned and
audited but not yet claim-ready; the strict gate, current blockers, and resume
commands are tracked in
[`docs/benchmark_regeneration_handoff.md`](docs/benchmark_regeneration_handoff.md).

## Models

| Model | Use |
| --- | --- |
| `spotlight_reflex` | Checkpoint-free smoke-test adapter. |
| `token_dagger_bc` | Learned policy adapter; requires `--checkpoint`. |
| `direct_actor_planner` | Planner adapter; requires `--oracle-actor-proxy`. |

## Commands

| Command | Purpose |
| --- | --- |
| `wod2sim-doctor` | Validate package install and optional AlpaSim environment. |
| `wod2sim-setup` | Wire WOD2Sim into a local AlpaSim checkout. |
| `wod2sim-ready` | Validate AlpaSim runtime and scene readiness. |
| `wod2sim-launch` | Print or launch AlpaSim external-driver runs. |
| `wod2sim-reproduce` | Plan or execute the full closed-loop evidence workflow. |
| `wod2sim-batch` | Run multi-scene closed-loop batches. |
| `wod2sim-audit-run` | Summarize executed run logs and sensor freshness. |
| `wod2sim-support-bundle` | Package key run logs, configs, and audit output. |

The full surface — benchmark planning, readiness, status, audit, promotion,
and cache tooling — is documented in
[`docs/cli_reference.md`](docs/cli_reference.md).

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

```bash
make test     # pytest suite
make verify   # lint + coverage + smoke + build + paper
make paper    # build paper/paper.pdf and copy ./arxiv.pdf
make clean    # remove generated local artifacts
```

## Citation

If you use this repository in academic work, cite the software metadata in
[`CITATION.cff`](CITATION.cff), the LaTeX source under [`paper/`](paper), and
the arXiv-ready PDF at [`arxiv.pdf`](arxiv.pdf).

## License

BSD 3-Clause. Some packaged AlpaSim override files carry separate third-party
notices; see [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).
