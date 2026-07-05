# Waymo-Readiness Notes

This repo should not be framed as something Waymo would adopt directly today.
It is a WOD-style-policy to AlpaSim bridge and evidence workflow, not a Waymo
simulator, planner, dataset product, or production evaluation stack.

For the dataset/simulator positioning, see
[`waymo_motion_and_alpasim.md`](waymo_motion_and_alpasim.md).

## Current Strength

- The public adapters can be installed as a normal Python package.
- The AlpaSim integration path now has a single evidence command:
  `wod2sim-reproduce`.
- A real one-scene local closed-loop run has been recorded as a compact evidence
  summary under [`docs/evidence/`](evidence/).
- Dry-run manifests make the command sequence auditable without private assets.

## Why Waymo Still Would Not Use It As-Is

- It targets NVIDIA AlpaSim, while Waymo has its own internal simulation and
  evaluation infrastructure.
- The strongest result still depends on gated local assets that cannot be
  redistributed in this repository.
- The recorded evidence is one public adapter on one local scene, not a broad
  benchmark over WOD-derived scenarios.
- The learned-policy artifacts are user-supplied rather than published,
  versioned, and evaluated at scale.
- The adapter surface is useful, but not yet a simulator-agnostic benchmark or
  model-quality result.

## What Would Make It More Relevant

The next credible milestone is not more README language. It is a reproducible
benchmark packet over user-provided assets:

- a declared scene set, preferably `front_camera_10scene_smoke` first
- exact `wod2sim-batch --mode both` or `wod2sim-reproduce --execute` command lines
- one manifest per run with git/package/runtime provenance
- support-bundle hashes and audit summaries
- aggregate metrics copied into compact `wod2sim-batch-summary` and
  `wod2sim-benchmark-summary` JSON
- a clear statement of which assets were local/gated and therefore not shipped

After that, the stronger milestone is a simulator-neutral interface: the same
policy-facing signal contract and trajectory output should be adaptable to more
than AlpaSim. That would make the repo more like a benchmark adapter layer and
less like infrastructure for one external simulator.

## Benchmark Protocol

Use this as the minimum evidence protocol for claims stronger than "the package
installs":

```bash
wod2sim-reproduce \
  --execute \
  --alpasim-root /path/to/alpasim \
  --model spotlight_reflex \
  --scene-preset front_camera_10scene_smoke \
  --run-dir runs/benchmark_spotlight_reflex_10scene \
  --evidence-dir runs/benchmark_spotlight_reflex_10scene/evidence \
  --timeout 900 \
  --json
```

For learned models, add the artifact path:

```bash
wod2sim-reproduce \
  --execute \
  --alpasim-root /path/to/alpasim \
  --model token_dagger_bc \
  --checkpoint /path/to/token_dagger_bc.pt \
  --scene-preset front_camera_10scene_smoke \
  --run-dir runs/benchmark_token_dagger_bc_10scene \
  --evidence-dir runs/benchmark_token_dagger_bc_10scene/evidence \
  --timeout 900 \
  --json
```

After all runs finish, publish a compact summary instead of raw gated artifacts:

```bash
wod2sim-batch \
  --mode both \
  --model spotlight_reflex \
  --scene-preset front_camera_10scene_smoke \
  --alpasim-root /path/to/alpasim \
  --batch-dir runs/benchmark_spotlight_reflex_10scene \
  --timeout 900 \
  --driver-warmup-seconds 5 \
  --max-retries 1 \
  --continue-on-error

wod2sim-batch-summary \
  --batch-dir runs/benchmark_spotlight_reflex_10scene \
  --output runs/benchmark_spotlight_reflex_10scene/wod2sim-batch-summary.json \
  --strict \
  --json

wod2sim-benchmark-summary \
  --evidence-dir runs/benchmark_spotlight_reflex_10scene/evidence \
  --evidence-dir runs/benchmark_token_dagger_bc_10scene/evidence \
  --output runs/wod2sim-benchmark-summary.json \
  --strict \
  --json
```

Publish only redistributable summaries unless you have explicit rights to share
the underlying AlpaSim/WOD-derived artifacts. At minimum, publish:

- `closed-loop-reproduction-manifest.json`
- `run-audit.json`
- `support-bundle-report.json`
- `wod2sim-benchmark-summary.json`
- `wod2sim-batch-summary.json`
- support-bundle SHA256
- aggregate metric text or a manually extracted metric table
- exact WOD2Sim commit SHA and package version

## Scene-Scale Path

Use the 10-scene preset first to validate runtime stability and evidence
generation. The larger public-scene presets are:

| Preset | Purpose |
| --- | --- |
| `front_camera_10scene_smoke` | Local pilot and screenshot/evidence generation. |
| `front_camera_50scene_public2602` | Workshop-scale batch once scene cache and token access are ready. |
| `front_camera_100scene_public2602` | Stronger systems benchmark claim with the same public AlpaSim catalog. |

The 50/100-scene presets still require local access to the public AlpaSim scene
artifacts, typically through a populated Hugging Face cache or an `HF_TOKEN`.

The current public evidence artifact is
[`docs/evidence/closed_loop_spotlight_reflex_10scene_batch.json`](evidence/closed_loop_spotlight_reflex_10scene_batch.json).
It records a completed 10-scene `spotlight_reflex` pilot with 1,990 audited
frames, 0 failed scenes, and 0 sensor-pipeline failures while keeping raw
AlpaSim/WOD-derived media out of git.
