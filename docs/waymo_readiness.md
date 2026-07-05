# Waymo-Readiness Notes

This repo should not be framed as something Waymo would adopt directly today.
It is a WOD-style-policy to AlpaSim bridge and evidence workflow, not a Waymo
simulator, planner, dataset product, or production evaluation stack.

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
- exact `wod2sim-reproduce --execute` command lines
- one manifest per run with git/package/runtime provenance
- support-bundle hashes and audit summaries
- aggregate metrics copied into a compact, redistributable summary
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

Publish only redistributable summaries unless you have explicit rights to share
the underlying AlpaSim/WOD-derived artifacts. At minimum, publish:

- `closed-loop-reproduction-manifest.json`
- `run-audit.json`
- `support-bundle-report.json`
- support-bundle SHA256
- aggregate metric text or a manually extracted metric table
- exact WOD2Sim commit SHA and package version
