# Getting Started

AlpaBridge is an external-driver adapter for an existing AlpaSim checkout. It
does not install AlpaSim or ship policy checkpoints. It also doesn't bundle
gated scene data, but it does provide a tool to download it with your own
access (see Get Scene Data below) — this repo never redistributes it itself.

For the fastest path from zero to a running rollout, start with the [main
README](../README.md#install--connect-alpasim) instead; this doc adds launch
commands for presets the README doesn't spell out (`token_dagger_bc`,
`direct_actor_planner`).

## Requirements

- Python 3.10 or newer.
- For live rollouts: x86_64 Linux, Docker, NVIDIA Container Toolkit, and a GPU.
- A local [AlpaSim](https://github.com/NVlabs/alpasim) checkout with scene assets.
- Optional gated extensions: a Token BC/DAgger checkpoint for learned runs or
  a scene-matched actor proxy for direct-planner runs.

The simple, no-setup public core uses `constant_velocity` and
`route_following`; neither needs a learned checkpoint or direct-planner
actor proxy.

## Install

```bash
uv sync
uv run alpabridge-doctor --strict-installed --json
```

`uv sync` uses the tracked `uv.lock` dependency snapshot. Contributing to
AlpaBridge itself (not just using it) needs the dev tooling instead: `uv sync
--extra dev` — see [Contributing](../.github/CONTRIBUTING.md).

## Connect AlpaSim

Inspect the changes before applying them:

```bash
alpabridge-setup --alpasim-root /path/to/alpasim --check-only
```

Apply the tracked override layer and validate the environment:

```bash
alpabridge-setup --alpasim-root /path/to/alpasim
alpabridge-ready --alpasim-root /path/to/alpasim --scene-preset fresh_3scene
```

## Get Scene Data

`alpabridge-ready` above reports whether the scenes your preset needs are
already cached locally. If they aren't, see the [main README's Get Scene
Data](../README.md#get-scene-data) section — real scene files come from a
gated Hugging Face dataset, fetched with `alpabridge-build-local-cache`.

This is specific to that one catalog (NVIDIA's NuRec/PhysicalAI dataset):
`--scene-preset` picks one of six fixed scene lists from it. `--scene-id`
(on `alpabridge-launch`, `alpabridge-ready`, and `alpabridge-build-local-cache`)
lets you target one specific scene from that same catalog instead of
fetching or running a whole preset — it still has to be a scene the
catalog already knows about, so it's not a way to plug in scene content of
your own. `--source-usdz-dir` (on `alpabridge-build-local-cache`) only
changes where the USDZ files are copied from (a local directory instead of
downloading) — same constraint applies. Registering genuinely new scene
content is an AlpaSim-side change, outside what this repo's tooling does.

## Materialize Commands

Simple, no-setup baseline:

```bash
alpabridge-launch \
  --mode print \
  --alpasim-root /path/to/alpasim \
  --model constant_velocity \
  --scene-preset fresh_3scene
```

Token BC/DAgger:

```bash
alpabridge-launch \
  --mode print \
  --alpasim-root /path/to/alpasim \
  --model token_dagger_bc \
  --checkpoint /path/to/token_dagger_bc.pt \
  --scene-preset fresh_3scene
```

Direct actor planner:

```bash
alpabridge-build-oracle-proxy \
  --alpasim-root /path/to/alpasim \
  --run-dir /path/to/completed-scene-matched-run \
  --output /tmp/alpabridge-actor-proxy.json

alpabridge-launch \
  --mode print \
  --alpasim-root /path/to/alpasim \
  --model direct_actor_planner \
  --oracle-actor-proxy /tmp/alpabridge-actor-proxy.json \
  --scene-preset fresh_3scene
```

The oracle actor proxy must come from the same scene family you plan to run.
Adapters reject proxy frames whose `scene_id` does not match the current
prediction scene, so a timestamp-only proxy from another rollout is diagnostic
input, not valid direct-planner evidence.

`--mode print` writes the driver config, driver command, wizard command, launch
metadata, and planned run status without starting Docker or a rollout. Review
those files before changing the mode to `both`.
