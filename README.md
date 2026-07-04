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

If you have a local AlpaSim checkout, the main bridge flow is:

```bash
python scripts/setup_alpasim_local_plugin.py --alpasim-root /path/to/alpasim
python scripts/check_alpasim_readiness.py --alpasim-root /path/to/alpasim
python scripts/run_alpasim_local_external.py --mode print --model spotlight_reflex
```

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
