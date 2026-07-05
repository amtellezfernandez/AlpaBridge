# Integration Guide

`WOD2Sim` is a standalone policy-adaptation repo, not a full simulator
distribution. The intended user is an engineer who already has access to an
AlpaSim checkout and wants a narrow, auditable path for adapting WOD-style
policies into closed-loop execution.

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

If you prefer the stdlib path instead, `python3 -m venv .venv` also works, but
on Debian/Ubuntu you may need the distro package first, for example
`sudo apt install python3.12-venv`.

2. Validate the release surface.

```bash
wod2sim-doctor
```

On a fresh machine where the nested checkout has not been cloned yet, start with:

```bash
wod2sim-doctor --probe-default-environment
```

That explicitly audits the documented default `workspace/alpasim` path and reports
host/runtime readiness even if the checkout is still missing.

3. Validate your AlpaSim environment with the same doctor path or the narrower readiness command.

```bash
wod2sim-doctor --alpasim-root /path/to/alpasim
```

or

```bash
wod2sim-ready --alpasim-root /path/to/alpasim
```

If you only want to validate host/runtime prerequisites before syncing gated assets, skip the scene-cache gate explicitly:

```bash
wod2sim-doctor --alpasim-root /path/to/alpasim --skip-scene-artifacts
```

4. Generate a non-executing launch plan first.

```bash
wod2sim-launch --mode print --model spotlight_reflex
```

`--mode print` only writes commands and metadata. It does not require local USDZ
scene artifacts or a live Docker/GPU rollout path.

5. If `fresh_3scene` is only partially cached, switch to the smaller cached smoke preset for the first real rollout.

```bash
wod2sim-doctor --alpasim-root /path/to/alpasim --scene-preset front_camera_10scene_smoke
wod2sim-launch --mode both --model spotlight_reflex --scene-preset front_camera_10scene_smoke
```

For a claim-verification run that records the exact commands, audit output, and
support bundle in one place, prefer:

```bash
wod2sim-reproduce --execute --alpasim-root /path/to/alpasim --model spotlight_reflex --scene-preset front_camera_10scene_smoke
```

The same command without `--execute` writes a plan-only manifest that does not
require private assets and does not count as closed-loop evidence. See
[`closed_loop_reproduction.md`](closed_loop_reproduction.md).

If you want the repo to prepare its own local `.venv` and wire the nested
AlpaSim checkout in one pass, use:

```bash
./scripts/bootstrap_alpasim_env.sh
```

That helper prefers `uv` when available, but it can also fall back to
`python3 -m venv` plus `pip`.

If you already have the gated USDZ cache in another local checkout, import it into
this repo's nested AlpaSim data tree with:

```bash
./scripts/import_alpasim_scene_cache.sh --source-root /path/to/other/alpasim
```

That path creates hardlinks by default, so the target checkout stays self-contained
inside the Docker-mounted tree instead of relying on absolute symlinks that break
container resolution.

## Supported Public Models

- `spotlight_reflex`
  - checkpoint-free
  - best first smoke test
- `token_dagger_bc`
  - requires `--checkpoint /path/to/token_dagger_bc.pt`
- `direct_actor_planner`
  - requires `--oracle-actor-proxy /path/to/oracle.json`
  - build that file with `wod2sim-build-oracle-proxy --run-dir /path/to/run --output /path/to/oracle.json`

## Expected Outputs

For `wod2sim-launch`, a successful planning pass creates a run directory containing:

- `launch-metadata.json`
- `run-status.json`
- `driver-command.sh`
- `wizard-command.sh`
- `external-driver-config.yaml`
- `driver/spotlight-log.jsonl`, `driver/selection-log.jsonl`, or `driver/direct-planner-log.jsonl`
  depending on the model

The per-frame driver logs include a `sensor_freshness` object with the newest
camera timestamp, ego pose timestamp, pose-camera lag, and a status label such as
`ok_camera_advanced`, `stale_camera_timestamp`, or `frozen_camera_content`.
`run-status.json` records the launch phase, execution mode, return codes, and
whether aggregate rollout outputs were produced.

To summarize those logs after a run:

```bash
wod2sim-audit-run --run-dir /path/to/run
wod2sim-audit-run --run-dir /path/to/run --audit-dir /path/to/audit --json
```

The first form prints a human summary. The second also exports a normalized audit
bundle with `manifest.json` and `frames.jsonl`.

To package the key run artifacts for handoff or debugging on another machine:

```bash
wod2sim-support-bundle --run-dir /path/to/run
```

That command creates a `.tar.gz` bundle next to the run directory containing the
structured driver logs, launch metadata, driver/wizard command files, selected
controller and aggregate outputs, and the normalized audit export.

For `wod2sim-batch`, a successful planning or execution pass creates:

- `batch-manifest.json`
- `batch-status.json`
- one run directory per scene

`batch-status.json` now keeps a per-scene `diagnostics` block with:

- `run-status.json` state, phase, aggregate status, and return codes
- driver-log kind/path presence
- frame count
- sensor-pipeline status and first sensor failure when present

The batch summary also rolls up `status_counts`, `result_counts`, `run_state_counts`,
`aggregate_status_counts`, and `sensor_failure_runs` so failed scenes remain
actionable without opening each run directory by hand.

## Common Failures

- Docker daemon inaccessible
  - fix local Docker group or daemon availability before retrying
- `alpasim-base:0.66.0` missing
  - build it with `scripts/build_alpasim_base_image.sh`
- scene artifacts missing
  - sync the gated assets locally or provide `HF_TOKEN`
  - if another checkout already has the cache, run `./scripts/import_alpasim_scene_cache.sh --source-root /path/to/other/alpasim`
  - if you only need host/runtime validation first, rerun `wod2sim-doctor --alpasim-root /path/to/alpasim --skip-scene-artifacts`
- checkpoint not found
  - pass an explicit `--checkpoint` for `token_dagger_bc`
- oracle actor proxy missing
  - generate it before using `direct_actor_planner`
- `stale camera stream`
  - the ego pose advanced but camera timestamps did not
  - inspect the model-specific driver log under `run_dir/driver/` and check the
    `sensor_freshness` record before changing policy code
  - this is upstream of the policy adapter; inspect the AlpaSim/sensorsim camera pipeline instead of tuning the policy
- noisy `Skipping directory ... not recognized as job dir` aggregation messages
  - this can come from older local override payloads in an AlpaSim checkout
  - rerun `wod2sim-setup --alpasim-root /path/to/alpasim` so the tracked override layer is refreshed

## What This Repo Does Not Promise

- it does not ship AlpaSim itself
- it does not ship private checkpoints
- it does not ship gated scene assets
- it does not claim a dry-run, synthetic smoke, or `--mode print` plan is WOD-to-closed-loop evidence
- it does not claim that unpublished research presets are supported in the public release
