# Benchmark Evidence Workflow

This page documents the full benchmark regeneration tool chain: how multi-scene
closed-loop batches are run, summarized, audited, and promoted into the tracked
public evidence under [`docs/evidence/`](evidence/). For the current operator
handoff state (who can run what, current blockers), see
[`benchmark_regeneration_handoff.md`](benchmark_regeneration_handoff.md).

## Runtime Compatibility

| Task | Who Can Run It |
| --- | --- |
| Public package checks, dry reproduction plans, summaries | Any supported Python host; no AlpaSim assets required. |
| 26.02 local USDZ cache construction | Hosts with Hugging Face access, enough disk, and Python dependencies; GPU is not required. |
| Live AlpaSim closed-loop rollouts | x86_64 Linux hosts with Docker, NVIDIA GPU runtime, AlpaSim images, and cached scene artifacts. |
| ARM/Linux hosts | Supported for cache building and diagnostics only; live rollouts are blocked by default because the AlpaSim sensorsim image used here is amd64-only. |

Set `WOD2SIM_ALLOW_UNSUPPORTED_ALPASIM_ARM=1` only when intentionally testing an
unsupported ARM rollout path.

The generated operator matrix is tracked at
[`evidence/benchmark_operator_matrix_20260706.json`](evidence/benchmark_operator_matrix_20260706.json)
and records which roles can review, build caches, run live shards, or promote
claim artifacts from the current evidence state. It also mirrors the rendered
command artifact's `command_execution` counts so the role matrix shows how many
public-review, cache, live-rollout, merge, and promotion commands map to each
operator role. Its `resume_command_execution` section does the same for the
audit-derived missing-shard resume snapshot, while `resume_repair_scope`
summarizes the affected 50/100 stages and missing shard inputs.

## Building A Local USDZ Cache

For the larger 26.02 presets, first build a local USDZ directory from the
Hugging Face artifact revision. This uses each USDZ's `metadata.yaml` as the
source of truth and avoids relying on stale catalog UUIDs:

```bash
HF_TOKEN=... wod2sim-build-local-cache \
  --scene-preset front_camera_50scene_public2602 \
  --alpasim-root /path/to/alpasim \
  --local-usdz-dir /path/to/alpasim/data/nre-artifacts/local-2602-usdzs-50 \
  --workers 3
```

Validate the cache offline with `wod2sim-build-local-cache --validate-only`
before launching shards. The validation report includes `missing_scene_ids`,
`invalid_revision_scene_ids`, and `invalid_cache_files`; any non-empty list is a
pre-run stop condition for 50/100-scene shards.

## Running Multi-Scene Batches

Run scenes as independent statistical units:

```bash
wod2sim-batch \
  --mode both \
  --model spotlight_reflex \
  --scene-preset front_camera_50scene_public2602 \
  --alpasim-root /path/to/alpasim \
  --batch-dir runs/benchmark_spotlight_reflex_50scene_public2602_fresh \
  --timeout 900 \
  --driver-warmup-seconds 5 \
  --max-retries 1 \
  --continue-on-error \
  --wizard-arg scenes.local_usdz_dir=/path/to/alpasim/data/nre-artifacts/local-2602-usdzs-50
```

Then publish compact summaries instead of raw gated artifacts:

```bash
wod2sim-batch-summary \
  --batch-dir runs/benchmark_spotlight_reflex_10scene_fresh \
  --output runs/benchmark_spotlight_reflex_10scene_fresh/wod2sim-batch-summary.json \
  --strict \
  --json

wod2sim-benchmark-summary \
  --evidence-dir runs/benchmark_spotlight_reflex_10scene_fresh/evidence \
  --output runs/wod2sim-benchmark-summary.json \
  --strict \
  --json
```

Shard summaries can be merged with `wod2sim-batch-summary` using the
`--merge-summary` and `--expected-scene-count` options, then promoted with
`wod2sim-promote-batch-summary`.

## Tracked Evidence Artifacts

| Artifact | Regenerate With | Purpose |
| --- | --- | --- |
| [`evidence/benchmark_regeneration_status_20260706.json`](evidence/benchmark_regeneration_status_20260706.json) | `wod2sim-benchmark-status` | Public benchmark status from compact evidence artifacts; exposes `claim_ready`, `objective_completion`, and per-preset `scale_status` (local/source USDZ cache validity, matching scene counts). Only reads compact JSON artifacts; does not probe Docker, GPUs, or local scene caches. |
| [`evidence/benchmark_public_evidence_manifest_20260706.json`](evidence/benchmark_public_evidence_manifest_20260706.json) | `wod2sim-benchmark-evidence-manifest` | Hash/size/schema manifest for tracked compact evidence; excludes its own hash, records missing 50/100 expected claim summaries, and mirrors the audited missing-shard resume repair scope, remaining requirements, blocker IDs, and next command groups. |
| [`evidence/benchmark_regeneration_plan_20260706.json`](evidence/benchmark_regeneration_plan_20260706.json) | `wod2sim-benchmark-plan` | Machine-readable 10/50/100 rerun plan. |
| [`evidence/benchmark_regeneration_readiness_20260706.json`](evidence/benchmark_regeneration_readiness_20260706.json) | `wod2sim-benchmark-readiness` | No-download/no-rollout host readiness report. The public plan uses `--stable-public-snapshot` so exact volatile disk byte counts do not churn the tracked JSON; rounded GiB and the minimum-disk pass/fail result remain recorded. |
| [`evidence/benchmark_regeneration_commands_20260706.json`](evidence/benchmark_regeneration_commands_20260706.json) | `wod2sim-benchmark-commands` | Rendered all-stage command artifact. Its `execution_boundary_counts`, `operator_role_counts`, `public_review_command_count`, and `private_execution_command_count` fields separate public review commands from cache-building, live-rollout, merge, and promotion commands. |
| [`evidence/benchmark_regeneration_resume_commands_20260706.json`](evidence/benchmark_regeneration_resume_commands_20260706.json) | `wod2sim-benchmark-commands --resume-missing-shards-from-audit` | Audit-derived missing-shard resume snapshot. Its `resume_plan` lists affected 50/100 stages, missing shard summary paths, merge/promote/post repair steps with per-shard scene offsets and limits, validate-only cache preflight commands, completion-gate expectations, and per-stage `claim_gap` progress. |
| [`evidence/benchmark_regeneration_audit_20260706.json`](evidence/benchmark_regeneration_audit_20260706.json) | `wod2sim-benchmark-audit` | Strict claim gate. Merged shard summaries must list the planned shard summary inputs, and the readiness snapshot must match the audited stage summary state. Diagnostic scale-probe evidence is validated as non-claim evidence so it cannot satisfy the strict 50/100-scene gate by accident. |

The audit's `objective_completion` section lists the satisfied requirements, the
remaining 50/100-scene claim gaps, the blocking readiness IDs, and the next
command groups to run via `blocking_requirements`, `next_command_groups`, and
`next_command_renderer_groups`. It also includes `scale_claim_gaps`, a
per-50/100-stage summary of local/source cache validity, missing summary state,
local planned-shard summary progress, blockers, and the next command groups
required before a claim can pass.

## Recorded Runs

| Artifact | What It Records |
| --- | --- |
| [`evidence/closed_loop_spotlight_reflex_one_scene.json`](evidence/closed_loop_spotlight_reflex_one_scene.json) | One-scene `spotlight_reflex` run: 199 audited frames, 0 sensor failures. |
| [`evidence/closed_loop_spotlight_reflex_10scene_batch.json`](evidence/closed_loop_spotlight_reflex_10scene_batch.json) | Claim-valid 10-scene pilot: 10/10 scenes, 1,990 audited frames, full failure taxonomy. |
| [`evidence/closed_loop_spotlight_reflex_50scene_localprobe_1scene.json`](evidence/closed_loop_spotlight_reflex_50scene_localprobe_1scene.json) | Diagnostic one-scene probe from the 50-scene public 26.02 preset. Scale-path evidence only; it is not a claim-valid 50-scene summary and does not satisfy the strict audit gate. |
| [`evidence/closed_loop_spotlight_reflex_50scene_attempt_partial.json`](evidence/closed_loop_spotlight_reflex_50scene_attempt_partial.json) | Earlier partial 50-scene attempt, tracked as non-claim evidence: 2/50 attempted scenes failed before audited frames were produced. |

Raw rollout media and support bundles are not tracked because they may contain
AlpaSim or gated-scene-derived content.

## Rendering Commands And Resuming Shards

Use `wod2sim-benchmark-commands` to render copyable command lines for a selected
stage, group, or shard directly from the tracked plan without duplicating the
long shard sequence in docs. Short setup groups include copyable `display`
commands; long shard groups stay referenced through the full plan. The renderer
includes 10-scene shard commands for the 50/100-scene stages so constrained
hosts can recover in smaller chunks while still preserving the full-stage claim
boundary.

To resume only shard work that the current audit marks missing or invalid:

```bash
wod2sim-benchmark-commands --resume-missing-shards-from-audit --group shards --json
```

Add `--stage` or `--shard-index` to narrow the output.

## Promotion Order

After promoting new public summaries with `wod2sim-promote-batch-summary`:

1. Refresh readiness with `wod2sim-benchmark-readiness`.
2. Regenerate status with `wod2sim-benchmark-status`.
3. Run `wod2sim-benchmark-audit --strict --json`.

This order avoids any circular dependency between the status and audit
artifacts. Open-repo reviewers can inspect every tracked artifact without
runtime access; cache rebuilds and live rollouts remain limited to operators
with gated assets and an x86_64 NVIDIA/Docker AlpaSim host.
