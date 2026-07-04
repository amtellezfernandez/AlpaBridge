# WOD2Sim

`WOD2Sim` packages the code and paper for adapting WOD-style driving policies to
AlpaSim's closed-loop external-driver runtime.

This repo is code-first. The paper is included under [`paper/`](paper), but the main
release surface is:

- installable Python package under [`src/minimal_shot_av/`](src/minimal_shot_av)
- AlpaSim bridge scripts under [`scripts/`](scripts)
- tracked patched-upstream AlpaSim layer under [`third_party/alpasim_overrides/`](third_party/alpasim_overrides)
- contract tests under [`tests/`](tests)

## What Is In Scope

- AlpaSim model adapters:
  `spotlight_reflex`, `token_dagger_bc`, and `direct_actor_planner`
- policy-facing signal reconstruction from AlpaSim prediction inputs
- route-waypoint bridge behavior and tracked upstream patch files
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

Or with `uv`:

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

Run the lightweight bridge checks:

```bash
make test
```

Smoke-test the public release surface:

```bash
make smoke
```

If you also want the same command to diagnose a real AlpaSim checkout:

```bash
wod2sim-doctor --alpasim-root /path/to/alpasim
```

If you have a local AlpaSim checkout, the main bridge flow is:

```bash
wod2sim-doctor
wod2sim-setup --alpasim-root /path/to/alpasim
wod2sim-ready --alpasim-root /path/to/alpasim
wod2sim-launch --mode print --model spotlight_reflex
```

## Public Model Surface

This release intentionally exposes a small public launch surface:

- `spotlight_reflex`: checkpoint-free smoke-test adapter
- `token_dagger_bc`: learned policy adapter; requires `--checkpoint /path/to/token_dagger_bc.pt`
- `direct_actor_planner`: planner adapter; requires `--oracle-actor-proxy /path/to/oracle.json`

Research-only presets from the original private tree are not advertised in the public CLI for this repo.

Examples:

```bash
wod2sim-launch --mode print --model spotlight_reflex
wod2sim-launch --mode print --model token_dagger_bc --checkpoint /path/to/token_dagger_bc.pt
wod2sim-launch --mode print --model direct_actor_planner --oracle-actor-proxy /path/to/oracle.json
```

For a fuller first-time setup path and failure triage notes, see
[`docs/integration_guide.md`](docs/integration_guide.md).

## Repo Layout

- [`src/minimal_shot_av/simulator/`](src/minimal_shot_av/simulator) contains the
  simulator logic and AlpaSim adapters.
- [`src/minimal_shot_av/cli/commands/`](src/minimal_shot_av/cli/commands) contains the
  bridge-facing command implementations.
- [`scripts/`](scripts) provides top-level entry wrappers for the public workflows.
- [`third_party/alpasim_overrides/`](third_party/alpasim_overrides) contains the tracked
  patched-upstream files and patch sets needed by the reproduction path.
- [`paper/`](paper) contains the LaTeX source and compiled PDF for the paper.

## Paper

Build the paper with:

```bash
make paper
```

The resulting source and PDF live under [`paper/`](paper).

## Release Checks

Run the public verification path with:

```bash
make verify
```

Clean generated local artifacts with:

```bash
make clean
```

## Production Notes

- The GitHub CI runs focused bridge tests, package build, and paper build.
- Learned presets still depend on external checkpoints not shipped in this repo.
- Full AlpaSim execution still requires a separate checkout, local Docker access, and any gated scene assets.
