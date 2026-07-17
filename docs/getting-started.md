# Getting Started

WOD2Sim is a contract-integration package for an existing AlpaSim checkout. It
does not install AlpaSim, download gated scenes, or ship policy checkpoints.

## Requirements

- Python 3.10 or newer.
- For live rollouts: x86_64 Linux, Docker, NVIDIA Container Toolkit, and a GPU.
- A local [AlpaSim](https://github.com/NVlabs/alpasim) checkout with scene assets.
- Optional for learned runs: a Token BC/DAgger checkpoint or a direct-planner actor proxy.

## Install

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
wod2sim-doctor --strict-installed --json
```

## Connect AlpaSim

Inspect the changes before applying them:

```bash
wod2sim-setup --alpasim-root /path/to/alpasim --check-only
```

Apply the tracked override layer and validate the environment:

```bash
wod2sim-setup --alpasim-root /path/to/alpasim
wod2sim-ready --alpasim-root /path/to/alpasim --scene-preset fresh_3scene
```

## Materialize Commands

Dependency-light baseline:

```bash
wod2sim-launch \
  --mode print \
  --alpasim-root /path/to/alpasim \
  --model constant_velocity \
  --scene-preset fresh_3scene
```

Token BC/DAgger:

```bash
wod2sim-launch \
  --mode print \
  --alpasim-root /path/to/alpasim \
  --model token_dagger_bc \
  --checkpoint /path/to/token_dagger_bc.pt \
  --scene-preset fresh_3scene
```

Direct actor planner:

```bash
wod2sim-build-oracle-proxy \
  --alpasim-root /path/to/alpasim \
  --run-dir /path/to/completed-scene-matched-run \
  --output /tmp/wod2sim-actor-proxy.json

wod2sim-launch \
  --mode print \
  --alpasim-root /path/to/alpasim \
  --model direct_actor_planner \
  --oracle-actor-proxy /tmp/wod2sim-actor-proxy.json \
  --scene-preset fresh_3scene
```

The oracle actor proxy must come from the same scene family you plan to run.
Adapters reject proxy frames whose `scene_id` does not match the current
prediction scene, so a timestamp-only proxy from another rollout is diagnostic
input, not valid direct-planner evidence.

`--mode print` writes the driver config, driver command, wizard command, launch
metadata, and planned run status without starting Docker or a rollout. Review
those files before changing the mode to `both`.
