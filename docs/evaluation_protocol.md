# Evaluation Protocol

WOD2Sim is an adapter and evidence layer for closed-loop evaluation. It should
not be read as a new autonomous driving policy, a new simulator, or a full
Waymo-to-AlpaSim scene converter.

The precise claim is:

> WOD2Sim bridges WOD-style policy interfaces to AlpaSim closed-loop execution
> and records the artifacts needed to audit that execution.

## Claim Boundary

Supported claims:

- A WOD-style trajectory policy can be exposed as an AlpaSim external driver.
- Route geometry, launch state, and simulator lifecycle behavior can be made
  explicit at the driver boundary.
- Closed-loop runs can emit manifests, audits, support-bundle reports, hashes,
  and benchmark summaries without redistributing gated assets.

Unsupported claims:

- WOD2Sim is not a new driving model.
- WOD2Sim is not a full Waymo Open Dataset scene-to-AlpaSim converter.
- WOD2Sim does not redistribute Waymo data, AlpaSim assets, private
  checkpoints, rollout videos, support bundles, or gated scene-derived files.
- Dry-run plans and one-off diagnostics are review artifacts, not broad
  benchmark results.

## Baselines

Use these baselines when making benchmark claims:

| Baseline | Purpose |
| --- | --- |
| Open-loop WOD-style evaluation | Shows what log-only evaluation can and cannot reveal. |
| Replay policy | Checks simulator plumbing without policy intelligence. |
| Constant-velocity or route-following driver | Provides a closed-loop sanity baseline. |
| Stock AlpaSim external-driver path | Shows what the WOD2Sim adapter adds. |
| WOD2Sim without route reconstruction | Ablates route geometry preservation. |
| WOD2Sim without lifecycle hardening | Ablates robust session handling. |

The strongest result is a paired example where the same policy appears
acceptable under open-loop evaluation but fails differently under closed-loop
execution.

## Metrics

Closed-loop reports should include:

| Metric Group | Examples |
| --- | --- |
| Driving outcome | collision rate, off-road rate, route progress, scenario completion, timeout rate |
| Runtime validity | valid-frame ratio, sensor freshness, action latency, late-message rate |
| Evidence validity | manifest present, audit valid, support bundle valid, support bundle hash present |
| Failure taxonomy | route drift, stale observations, heading-error compounding, recovery failure, lifecycle crash |

`wod2sim-batch-summary` is the compact artifact for multi-scene AlpaSim
batches. It reports per-scene completion, audited frames, closed-loop metric
rates, failure taxonomy, and local artifact hashes without embedding rollout
videos or scene assets.

## Scene Coverage

A workshop-scale evaluation should cover at least a small multi-scene set across
straight driving, turns, dense traffic, route merges, occlusion, and stop/go
cases. A stronger benchmark claim should scale to dozens of scenes and report
success/failure counts per route type.

| Stage | Preset | Claim Strength |
| --- | --- | --- |
| Pilot | `front_camera_10scene_smoke` | Runtime stability and concrete closed-loop evidence. |
| Workshop-scale | `front_camera_50scene_public2602` | Multi-scene failure taxonomy and baseline comparison. |
| Stronger benchmark | `front_camera_100scene_public2602` | More credible aggregate rates and scenario diversity. |

The 50/100-scene stages require a metadata-valid local AlpaSim USDZ directory,
gated scene access, and an x86_64 NVIDIA/Docker AlpaSim runner. ARM/Linux hosts
can build caches and run diagnostics, but live sensorsim rollouts are disabled
by default because the required sensorsim image is amd64-only.

Set `WOD2SIM_ALLOW_UNSUPPORTED_ALPASIM_ARM=1` only for an intentional
unsupported ARM rollout diagnostic.

## Current Public State

The tracked 10-scene `spotlight_reflex` pilot is valid integration evidence:

| Artifact | Result |
| --- | --- |
| [`docs/evidence/closed_loop_spotlight_reflex_10scene_batch.json`](evidence/closed_loop_spotlight_reflex_10scene_batch.json) | 10/10 completed scenes, 1,990 audited frames, 0 failed scenes, 0 sensor-pipeline failures. |
| [`docs/evidence/closed_loop_spotlight_reflex_50scene_localprobe_1scene.json`](evidence/closed_loop_spotlight_reflex_50scene_localprobe_1scene.json) | Diagnostic 50-preset local probe only: 1/1 completed scene, 199 audited frames, 0 sensor-pipeline failures. Not a 50-scene claim summary. |
| [`docs/evidence/closed_loop_spotlight_reflex_50scene_attempt_partial.json`](evidence/closed_loop_spotlight_reflex_50scene_attempt_partial.json) | Diagnostic partial 50-preset attempt only: 2/50 attempted scenes failed before audited frames were produced. Not a 50-scene claim summary. |
| Failure taxonomy | 5 collision scenes, 2 at-fault collision scenes, 3 wrong-lane scenes, 0 offroad scenes, 7 low-progress scenes. |

The 50- and 100-scene public 26.02 stages are planned but not claim-ready. The
current status tracks the 50/100 cache and summary gap explicitly:
`scale_status.<preset>.source_usdz_cache`,
`scale_status.<preset>.local_usdz_cache`, and the summary state. The tracked
`source_usdz_cache.matching_scene_count` is `0` for both presets after source
cache cleanup. The local 50-scene cache is independently valid at 50/50; the
local 100-scene cache remains invalid at 0/100. Neither scale stage has a
claim-valid summary.

## Regeneration Artifacts

The current evidence chain is machine-readable and public-safe:

| Artifact | Purpose |
| --- | --- |
| [`docs/evidence/benchmark_regeneration_plan_20260706.json`](evidence/benchmark_regeneration_plan_20260706.json) | 10/50/100 rerun plan, scene presets, shard boundaries, merge commands, and promotion targets. |
| [`docs/evidence/benchmark_regeneration_readiness_20260706.json`](evidence/benchmark_regeneration_readiness_20260706.json) | No-download/no-rollout host readiness snapshot. |
| [`docs/evidence/benchmark_regeneration_status_20260706.json`](evidence/benchmark_regeneration_status_20260706.json) | Public benchmark status, `claim_ready`, objective-completion fields, and per-preset scale status. |
| [`docs/evidence/benchmark_regeneration_commands_20260706.json`](evidence/benchmark_regeneration_commands_20260706.json) | Rendered cache, shard, merge, promotion, status, and audit commands. Its `execution_boundary_counts`, `operator_role_counts`, `public_review_command_count`, and `private_execution_command_count` separate public review from private cache/rollout/promotion work. |
| [`docs/evidence/benchmark_regeneration_resume_commands_20260706.json`](evidence/benchmark_regeneration_resume_commands_20260706.json) | Audit-derived resume commands for missing or invalid planned 50/100 shard summaries. |
| [`docs/evidence/benchmark_regeneration_audit_20260706.json`](evidence/benchmark_regeneration_audit_20260706.json) | Strict claim gate over summaries, readiness, public handoff, manifest hashes, and diagnostic non-claim evidence. |
| [`docs/evidence/benchmark_public_evidence_manifest_20260706.json`](evidence/benchmark_public_evidence_manifest_20260706.json) | Hash/size/schema manifest for compact public evidence and expected missing 50/100 claim summaries. |
| [`docs/evidence/benchmark_operator_matrix_20260706.json`](evidence/benchmark_operator_matrix_20260706.json) | Role matrix for public review, cache building, live rollouts, merge, and promotion. |
| [`docs/benchmark_regeneration_handoff.md`](benchmark_regeneration_handoff.md) | Human handoff with blocker IDs, role boundaries, current command groups, cleanup boundary, and promotion boundary. |

Use [`benchmark_evidence_workflow.md`](benchmark_evidence_workflow.md) for the
copyable cache, batch, merge, promotion, status, and audit workflow. Short setup
groups include display commands; long shard groups are rendered from the plan
with `wod2sim-benchmark-commands --group shards` to avoid duplicating every
shard command in prose.

## Publication Rule

Public releases should publish compact JSON summaries, metric tables, hashes,
and redistribution-cleared images only. Do not publish raw USDZ assets, rollout
videos, Docker layers, Hugging Face caches, or support bundles containing gated
content.
