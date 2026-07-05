# WOD2Sim

[![CI](https://github.com/amtellezfernandez/wayspan/actions/workflows/ci.yml/badge.svg)](https://github.com/amtellezfernandez/wayspan/actions/workflows/ci.yml)
[![License: BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-blue.svg)](LICENSE)

`WOD2Sim` packages the code and paper for adapting WOD-style driving policies to
AlpaSim's closed-loop external-driver runtime.

It is a standalone policy-adaptation repo. It does not import or depend on any
larger research tree at runtime.

This repo is code-first. The paper is included under [`paper/`](paper), but the main
release surface is:

- installable Python package under [`src/wod2sim/`](src/wod2sim)
- AlpaSim runtime scripts under [`scripts/`](scripts)
- tracked AlpaSim override layer under [`third_party/alpasim_overrides/`](third_party/alpasim_overrides)
- contract tests under [`tests/`](tests)

## What Is In Scope

- AlpaSim model adapters:
  `spotlight_reflex`, `token_dagger_bc`, and `direct_actor_planner`
- policy-facing signal reconstruction from AlpaSim prediction inputs
- route-waypoint adapter behavior and tracked AlpaSim override files
- local setup, readiness, launch, and scene-batch orchestration
- simulator-side policy code used by the adapter surface
- the paper and its build assets

## What Is Not Bundled

- AlpaSim itself: this repo expects a separate nested AlpaSim checkout
- private checkpoints or large local artifacts from the original research tree
- gated scene assets and local Docker images

## Quick Start

Create a Python environment and install the package in editable mode:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev]"
```

On Debian/Ubuntu hosts, if `python3 -m venv .venv` fails because `ensurepip` is
unavailable, install the distro venv package first, for example
`sudo apt install python3.12-venv`.

Or with `uv`:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

Run the lightweight repo checks:

```bash
make test
```

Smoke-test the public release surface:

```bash
make smoke
```

That smoke path now performs a fresh-checkout bootstrap audit: it copies the repo
into a temporary checkout, installs `.[dev]` into a clean venv, and runs the
documented non-AlpaSim commands from that isolated environment.

If you also want the same command to diagnose a real AlpaSim checkout:

```bash
wod2sim-doctor --alpasim-root /path/to/alpasim
```

If that checkout is not fully synced yet and you only want host/runtime validation:

```bash
wod2sim-doctor --alpasim-root /path/to/alpasim --skip-scene-artifacts
```

If you are auditing a fresh machine before the checkout exists, probe the default
host/runtime path first:

```bash
wod2sim-doctor --probe-default-environment
```

That mode reports whether Docker, the local `alpasim-base:0.66.0` image, and the
NVIDIA container runtime are ready, while making the missing checkout an explicit
failing status instead of hiding it behind `environment: null`.

If you have a local AlpaSim checkout, the main runtime flow is:

```bash
wod2sim-doctor
wod2sim-setup --alpasim-root /path/to/alpasim
wod2sim-ready --alpasim-root /path/to/alpasim
wod2sim-launch --mode print --model spotlight_reflex
```

If `fresh_3scene` is not fully cached yet, a more reliable first live smoke is:

```bash
wod2sim-doctor --alpasim-root /path/to/alpasim --scene-preset front_camera_10scene_smoke
wod2sim-launch --mode both --model spotlight_reflex --scene-preset front_camera_10scene_smoke
```

For the evidence-oriented closed-loop reproduction workflow, use:

```bash
wod2sim-reproduce --execute --alpasim-root /path/to/alpasim --model spotlight_reflex
```

Without `--execute`, the same command writes a public command manifest without
requiring private AlpaSim assets. See
[`docs/closed_loop_reproduction.md`](docs/closed_loop_reproduction.md) for the
claim boundary, gated-asset requirements, and recorded evidence format.
One compact recorded evidence summary is tracked at
[`docs/evidence/closed_loop_spotlight_reflex_one_scene.json`](docs/evidence/closed_loop_spotlight_reflex_one_scene.json).

If you already have the gated USDZ cache in another local checkout, import it into
this repo's nested AlpaSim tree without Docker-breaking absolute symlinks:

```bash
./scripts/import_alpasim_scene_cache.sh --source-root /path/to/other/alpasim
```

## Public Model Surface

This release intentionally exposes a small public launch surface:

- `spotlight_reflex`: checkpoint-free smoke-test adapter
- `token_dagger_bc`: learned policy adapter; requires `--checkpoint /path/to/token_dagger_bc.pt`
- `direct_actor_planner`: planner adapter; requires `--oracle-actor-proxy /path/to/oracle.json`

Research-only presets outside this release are not advertised in the public CLI.

Examples:

```bash
wod2sim-build-oracle-proxy --run-dir /path/to/run --output /path/to/oracle.json
wod2sim-launch --mode print --model spotlight_reflex
wod2sim-launch --mode print --model token_dagger_bc --checkpoint /path/to/token_dagger_bc.pt
wod2sim-launch --mode print --model direct_actor_planner --oracle-actor-proxy /path/to/oracle.json
```

After an executed run, summarize the public driver logs with:

```bash
wod2sim-audit-run --run-dir /path/to/run
wod2sim-audit-run --run-dir /path/to/run --audit-dir /path/to/audit --json
```

To package the key run logs, configs, and audit output into one shareable tarball:

```bash
wod2sim-support-bundle --run-dir /path/to/run
wod2sim-support-bundle --run-dir /path/to/run --output /tmp/run_support_bundle.tar.gz --json
```

For a fuller first-time setup path and failure triage notes, see
[`docs/integration_guide.md`](docs/integration_guide.md).

One important runtime invariant: if ego pose updates continue while camera timestamps stay frozen, the public adapters now fail fast with a `stale camera stream` error instead of silently planning on stale frames.
Each public model also writes a structured per-frame driver log under `run_dir/driver/`:
`spotlight-log.jsonl`, `selection-log.jsonl`, or `direct-planner-log.jsonl`.
Those records include `sensor_freshness` fields with the latest camera timestamp,
ego pose timestamp, lag, and failure status so upstream camera-pipeline faults are
auditable after the run.
Executed runs also write `run-status.json`, which records the launch mode, current
phase, return codes, aggregate-output status, and key log paths.
Batch runs now preserve a per-scene `diagnostics` block in `batch-status.json`
with each scene's `run-status` summary, driver-log presence, and first camera-pipeline
failure so multi-scene triage does not collapse to `partial` or `missing`.

## Repo Layout

- [`src/wod2sim/simulator/`](src/wod2sim/simulator) contains the
  simulator logic and AlpaSim adapters.
- [`src/wod2sim/cli/commands/`](src/wod2sim/cli/commands) contains the
  runtime-facing command implementations.
- [`scripts/`](scripts) provides top-level entry wrappers for the public workflows.
- [`third_party/alpasim_overrides/`](third_party/alpasim_overrides) contains the tracked
  AlpaSim override files and patch sets needed by the reproduction path.
- [`docs/closed_loop_reproduction.md`](docs/closed_loop_reproduction.md) documents
  the actual closed-loop evidence workflow and gated asset boundaries.
- [`paper/`](paper) contains the LaTeX source for the paper.

## Paper

Build the paper with:

```bash
make paper
```

The source lives under [`paper/`](paper). CI publishes the compiled PDF as a build
artifact instead of tracking generated PDFs in git.

## Release Checks

Run the public verification path with:

```bash
make verify
```

Clean generated local artifacts with:

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

## Production Notes

- The GitHub CI runs lint, coverage, package build, wheel smoke, and paper build.
- Learned presets still depend on external checkpoints not shipped in this repo.
- Full AlpaSim execution still requires a separate checkout, local Docker access, and any gated scene assets.
