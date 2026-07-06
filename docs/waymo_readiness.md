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
  --run-dir runs/benchmark_spotlight_reflex_10scene_fresh \
  --evidence-dir runs/benchmark_spotlight_reflex_10scene_fresh/evidence \
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
  --run-dir runs/benchmark_token_dagger_bc_10scene_fresh \
  --evidence-dir runs/benchmark_token_dagger_bc_10scene_fresh/evidence \
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
  --batch-dir runs/benchmark_spotlight_reflex_10scene_fresh \
  --timeout 900 \
  --driver-warmup-seconds 5 \
  --max-retries 1 \
  --continue-on-error

wod2sim-batch-summary \
  --batch-dir runs/benchmark_spotlight_reflex_10scene_fresh \
  --output runs/benchmark_spotlight_reflex_10scene_fresh/wod2sim-batch-summary.json \
  --strict \
  --json

wod2sim-benchmark-summary \
  --evidence-dir runs/benchmark_spotlight_reflex_10scene_fresh/evidence \
  --evidence-dir runs/benchmark_token_dagger_bc_10scene_fresh/evidence \
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
| `front_camera_50scene_public2602` | Workshop-scale batch once a local 26.02 USDZ cache is built. |
| `front_camera_100scene_public2602` | Stronger systems benchmark claim using the same validated public 26.02 catalog subset. |

The 50/100-scene presets require local access to public AlpaSim scene artifacts.
Build a metadata-valid local USDZ directory first:

```bash
HF_TOKEN=... wod2sim-build-local-cache \
  --scene-preset front_camera_50scene_public2602 \
  --alpasim-root /path/to/alpasim \
  --local-usdz-dir /path/to/alpasim/data/nre-artifacts/local-2602-usdzs-50
```

Then pass it to the batch runner:

```bash
wod2sim-batch ... \
  --scene-preset front_camera_50scene_public2602 \
  --wizard-arg scenes.local_usdz_dir=/path/to/alpasim/data/nre-artifacts/local-2602-usdzs-50
```

Use the right host role for the job:

| Role | What It Can Do |
| --- | --- |
| Reviewer | Run public tests, dry plans, summaries, and evidence audits without gated assets. |
| Cache builder | Build a metadata-valid 26.02 USDZ directory with Hugging Face access and disk capacity; GPU is optional. |
| Closed-loop runner | Run live AlpaSim batches on x86_64 Linux with Docker, NVIDIA GPU runtime, AlpaSim images, and cached scene artifacts. |
| ARM/Linux host | Build caches and run diagnostics, but live sensorsim rollouts are disabled by default because the required sensorsim image is amd64-only. |

The current machine-readable role matrix is
[`docs/evidence/benchmark_operator_matrix_20260706.json`](evidence/benchmark_operator_matrix_20260706.json).
Regenerate it with `wod2sim-benchmark-operators`; it only reads tracked compact
JSON and does not probe Docker, GPUs, caches, or gated assets.

`WAYSPAN_ALLOW_UNSUPPORTED_ALPASIM_ARM=1` is reserved for intentional unsupported
ARM rollout diagnostics.

The current public evidence artifact is
[`docs/evidence/closed_loop_spotlight_reflex_10scene_batch.json`](evidence/closed_loop_spotlight_reflex_10scene_batch.json).
It records a completed 10-scene `spotlight_reflex` pilot with 1,990 audited
frames, 0 failed scenes, and 0 sensor-pipeline failures while keeping raw
AlpaSim/WOD-derived media out of git.

A diagnostic one-scene 50-preset probe is tracked at
[`docs/evidence/closed_loop_spotlight_reflex_50scene_localprobe_1scene.json`](evidence/closed_loop_spotlight_reflex_50scene_localprobe_1scene.json).
It records 1/1 completed scene and 0 sensor-pipeline failures, but it is not a
claim-valid 50-scene summary and does not satisfy
`wod2sim-benchmark-audit --strict`.
The partial 50-scene attempt is tracked at
[`docs/evidence/closed_loop_spotlight_reflex_50scene_attempt_partial.json`](evidence/closed_loop_spotlight_reflex_50scene_attempt_partial.json);
it records 2/50 attempted scenes failing before audited frames were produced.

The current public-safe 10/50/100 rerun plan is
[`docs/evidence/benchmark_regeneration_plan_20260706.json`](evidence/benchmark_regeneration_plan_20260706.json).
The no-download/no-rollout host readiness snapshot is
[`docs/evidence/benchmark_regeneration_readiness_20260706.json`](evidence/benchmark_regeneration_readiness_20260706.json).
The public benchmark status is
[`docs/evidence/benchmark_regeneration_status_20260706.json`](evidence/benchmark_regeneration_status_20260706.json)
and is regenerated with `wod2sim-benchmark-status` after readiness and before
the strict audit.
The compact evidence manifest is
[`docs/evidence/benchmark_public_evidence_manifest_20260706.json`](evidence/benchmark_public_evidence_manifest_20260706.json)
and is regenerated with `wod2sim-benchmark-evidence-manifest`; it records hashes
and claim scopes for tracked public JSON while keeping the 50/100 missing
summary artifacts explicit.
The readiness/status flow includes `blocking_requirements` and
`next_command_groups` so operators can map missing cache/runtime prerequisites
back to plan command groups. Short setup groups include copyable `display`
commands; long shard groups point back to the full plan.
The plan includes readiness reporting, local-cache validation, 10-scene shard
commands for constrained x86_64 hosts, and public-safe merge/promotion commands
for shard summaries. Use `wod2sim-benchmark-commands` to render the exact
cache, shard, merge, promotion, status, and audit commands from that plan. The
tracked all-stage rendering is
[`docs/evidence/benchmark_regeneration_commands_20260706.json`](evidence/benchmark_regeneration_commands_20260706.json);
it is reviewable in open repos, while cache rebuilds and rollouts are only for
operators with gated assets and an x86_64 NVIDIA/Docker AlpaSim host.
The matching claim-readiness audit is
[`docs/evidence/benchmark_regeneration_audit_20260706.json`](evidence/benchmark_regeneration_audit_20260706.json).
It verifies the tracked summary artifacts, merged shard provenance, and the
readiness snapshot's stage-summary state against the regeneration plan. Its
scale gap rows also report local planned-shard summary progress for resumable
50/100 execution. After new 50/100 summaries are promoted, refresh readiness,
regenerate status, then run `wod2sim-benchmark-audit --strict --json`.
