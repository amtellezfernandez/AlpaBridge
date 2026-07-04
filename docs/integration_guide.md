# Integration Guide

`WOD2Sim` is a bridge repo, not a full simulator distribution. The intended user is an engineer who already has access to an AlpaSim checkout and wants a narrow, auditable path for adapting WOD-style policies into closed-loop execution.

## Day 0 Checklist

Before attempting launch, confirm:

- Python `>=3.10`
- local `uv` or `venv` workflow available
- Docker daemon is reachable from your user account
- NVIDIA container runtime is available for real closed-loop runs
- a real AlpaSim checkout exists at `ALPASIM_ROOT`
- gated scene artifacts are locally available or `HF_TOKEN` is set
- any model-specific external artifacts are available:
  - `token_dagger_bc`: a checkpoint path
  - `direct_actor_planner`: an oracle actor proxy JSON

## First Run

1. Install the package.

```bash
uv venv .venv
uv pip install --python .venv/bin/python -e ".[dev]"
```

2. Validate the release surface.

```bash
wod2sim-doctor
```

3. Validate your AlpaSim environment with the same doctor path or the narrower readiness command.

```bash
wod2sim-doctor --alpasim-root /path/to/alpasim
```

or

```bash
wod2sim-ready --alpasim-root /path/to/alpasim
```

4. Generate a non-executing launch plan first.

```bash
wod2sim-launch --mode print --model spotlight_reflex
```

## Supported Public Models

- `spotlight_reflex`
  - checkpoint-free
  - best first smoke test
- `token_dagger_bc`
  - requires `--checkpoint /path/to/token_dagger_bc.pt`
- `direct_actor_planner`
  - requires `--oracle-actor-proxy /path/to/oracle.json`

## Expected Outputs

For `wod2sim-launch`, a successful planning pass creates a run directory containing:

- `launch-metadata.json`
- `driver-command.sh`
- `wizard-command.sh`
- `external-driver-config.yaml`

For `wod2sim-batch`, a successful planning or execution pass creates:

- `batch-manifest.json`
- `batch-status.json`
- one run directory per scene

## Common Failures

- Docker daemon inaccessible
  - fix local Docker group or daemon availability before retrying
- `alpasim-base:0.66.0` missing
  - build it with `scripts/build_alpasim_base_image.sh`
- scene artifacts missing
  - sync the gated assets locally or provide `HF_TOKEN`
- checkpoint not found
  - pass an explicit `--checkpoint` for `token_dagger_bc`
- oracle actor proxy missing
  - generate it before using `direct_actor_planner`

## What This Repo Does Not Promise

- it does not ship AlpaSim itself
- it does not ship private checkpoints
- it does not ship gated scene assets
- it does not claim that research-only presets from the original private tree are supported in the public release
