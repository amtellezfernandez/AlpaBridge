# Benchmark Regeneration Handoff

This page is the public-safe operator handoff for the current WOD2Sim
`spotlight_reflex` closed-loop benchmark regeneration chain. It summarizes who
can review, who can build, who can run, and what remains blocked without
requiring Docker, AlpaSim, Hugging Face credentials, local USDZ caches, or raw
rollout artifacts.

The authoritative machine-readable inputs are:

| Artifact | Purpose |
| --- | --- |
| [`docs/evidence/benchmark_regeneration_plan_20260706.json`](evidence/benchmark_regeneration_plan_20260706.json) | Planned 10/50/100 stages, shard boundaries, merge commands, and promotion targets. |
| [`docs/evidence/benchmark_regeneration_status_20260706.json`](evidence/benchmark_regeneration_status_20260706.json) | Current public benchmark status, tracked evidence links, and objective-completion state. |
| [`docs/evidence/benchmark_regeneration_readiness_20260706.json`](evidence/benchmark_regeneration_readiness_20260706.json) | No-download/no-rollout readiness snapshot and blocking requirement IDs. |
| [`docs/evidence/benchmark_operator_matrix_20260706.json`](evidence/benchmark_operator_matrix_20260706.json) | Generated who-can-review/build/run/promote matrix, current ready/blocked summary, command execution counts by role, and resume repair scope for the missing 50/100 shard inputs. |
| [`docs/evidence/benchmark_regeneration_commands_20260706.json`](evidence/benchmark_regeneration_commands_20260706.json) | Rendered cache, shard, merge, promotion, status, and audit commands from the plan, including execution-boundary and operator-role counts. |
| [`docs/evidence/benchmark_regeneration_resume_commands_20260706.json`](evidence/benchmark_regeneration_resume_commands_20260706.json) | Audit-derived resume snapshot for missing or invalid planned 50/100 shard summaries. |
| [`docs/evidence/benchmark_regeneration_audit_20260706.json`](evidence/benchmark_regeneration_audit_20260706.json) | Strict claim gate for the tracked public evidence chain. |
| [`docs/evidence/benchmark_public_evidence_manifest_20260706.json`](evidence/benchmark_public_evidence_manifest_20260706.json) | Hash/size/schema manifest for compact public evidence, missing expected 50/100 claim summaries, audited resume repair scope, remaining requirements, blocker IDs, and next command groups. |

## Current State

The tracked 10-scene pilot is claim-valid:
[`docs/evidence/closed_loop_spotlight_reflex_10scene_batch.json`](evidence/closed_loop_spotlight_reflex_10scene_batch.json)
records 10/10 completed scenes, 1,990 audited frames, zero failed scenes, and
zero sensor-pipeline failures.

The 50/100-scene claim is not ready. The strict audit is expected to return
non-zero until both public summaries exist and pass the full-stage checks:

```bash
wod2sim-benchmark-audit --strict --json
```

Current expected missing claim summaries:

| Missing Artifact | Required For |
| --- | --- |
| `docs/evidence/closed_loop_spotlight_reflex_50scene_batch.json` | Full 50-scene public 26.02 claim. |
| `docs/evidence/closed_loop_spotlight_reflex_100scene_batch.json` | Full 100-scene public 26.02 claim. |

Current blocker IDs from readiness:

| Blocker ID | Blocks |
| --- | --- |
| `hf_token_missing` | Downloading the local 26.02 USDZ cache from gated Hugging Face assets. Operators with a complete local `all-usdzs` directory can use the offline link command instead. |
| `docker_daemon_unavailable` | Live AlpaSim SensorSim rollouts. The tracked public snapshot skips runtime probes, so this remains conservative until refreshed on a live runner. |
| `alpasim_base_image_missing` | Live AlpaSim SensorSim rollouts. The tracked public snapshot skips image inspection, so this remains conservative until refreshed on a live runner. |
| `nvidia_gpu_unavailable` | Live AlpaSim SensorSim rollouts. The tracked public snapshot skips `nvidia-smi`, so this remains conservative until refreshed on a live runner. |
| `docker_nvidia_runtime_unavailable` | Live AlpaSim SensorSim rollouts. The tracked public snapshot skips Docker runtime inspection, so this remains conservative until refreshed on a live runner. |
| `front_camera_50scene_public2602_cache_invalid` | 50-scene shard execution. |
| `front_camera_50scene_public2602_claim_summary_missing` | 50-scene claim promotion and strict audit readiness. |
| `front_camera_100scene_public2602_cache_invalid` | 100-scene shard execution. |
| `front_camera_100scene_public2602_claim_summary_missing` | 100-scene claim promotion and strict audit readiness. |

The offline cache-link path is tracked but not currently ready on this
workspace: after local cleanup, the public readiness snapshot sees 0 USDZ files
in the source directory and `source_usdz_cache.matching_scene_count` is `0` for both
`front_camera_50scene_public2602` and `front_camera_100scene_public2602`. A
cache builder needs either a complete local `all-usdzs` directory for those
presets or gated Hugging Face access.
The same cache inventory is mirrored in
[`docs/evidence/benchmark_regeneration_status_20260706.json`](evidence/benchmark_regeneration_status_20260706.json)
under `scale_status.<preset>.source_usdz_cache` and
`scale_status.<preset>.local_usdz_cache`. The status artifact also exposes
top-level `claim_ready=false` and compact `objective_completion` fields for
remaining requirements, blocker IDs, and next command groups; use those fields
for open-repo review without probing private paths or runtime state.

## Who Can Do What

| Role | Can Run Now From Public State | Can Do | Cannot Do |
| --- | --- | --- | --- |
| Open-repo reviewer | Yes | Run public tests, dry plans, status, command rendering, operator matrix rendering, manifest checks, and non-mutating audits. | Download gated USDZs, build private caches, or execute live SensorSim rollouts. |
| Cache builder | No | Hardlink selected 26.02 assets from an existing local `all-usdzs` directory, or build and validate caches after `HF_TOKEN` and disk prerequisites are available. | Produce claim-valid closed-loop summaries without a separate live runner. |
| Closed-loop runner | No | Execute 50/100 live shards after x86_64 Linux, Docker, NVIDIA runtime, AlpaSim images, and valid caches are available. | Publish a 50/100 claim until every planned shard is complete and merged. |
| Claim promoter | No | Promote completed compact summaries and refresh the public status/audit artifacts. | Promote missing, partial, or diagnostic summaries as full benchmark claims. |
| ARM/DGX Spark-style host | Preparation only | Build caches and run diagnostics that do not start the amd64 SensorSim container. | Run live SensorSim rollouts by default; the required image is amd64-only. |

## Next Command Groups

Render exact commands from the tracked plan instead of copying commands from this
page:

```bash
wod2sim-benchmark-commands --group all --json
wod2sim-benchmark-commands --group cleanup --json
wod2sim-benchmark-commands --resume-missing-shards-from-audit --group shards --json
wod2sim-benchmark-commands --group cache --stage front_camera_50scene_public2602 --json
wod2sim-benchmark-commands --group shards --stage front_camera_50scene_public2602 --json
wod2sim-benchmark-commands --group shards --stage front_camera_100scene_public2602 --json
```

The current readiness handoff expects these groups, in order. The renderer group
column tells operators which `wod2sim-benchmark-commands --group ...` filters to
request from the tracked plan.

| Order | Readiness Group | Renderer Groups | Purpose |
| --- | --- | --- | --- |
| 1 | `refresh_readiness` | `readiness` | Recompute no-download/no-rollout readiness before touching caches or rollouts. |
| 2 | `build_and_validate_scale_caches` | `cache` | Link 50/100 local USDZ caches from `all-usdzs` when already present, otherwise build them from gated assets, then validate. |
| 3 | `run_scale_shards_and_promote_summaries` | `shards`, `merge`, `promote` | Run all planned 50/100 shards, merge shard summaries, and promote compact public summaries. |
| 4 | `refresh_status` | `post` | Regenerate public benchmark status from tracked compact evidence. |
| 5 | `verify_claim_gate` | `post` | Run the strict audit; it must pass before claiming the full 10/50/100 benchmark. |

## Public Review Commands

These commands only read tracked compact artifacts and are safe for open-repo
review:

```bash
uv run --extra dev --extra alpasim pytest
uv run --extra dev --extra alpasim ruff check .
uv run --extra dev --extra alpasim wod2sim-benchmark-status --json
uv run --extra dev --extra alpasim wod2sim-benchmark-operators --json
uv run --extra dev --extra alpasim wod2sim-benchmark-cleanup --json
uv run --extra dev --extra alpasim wod2sim-benchmark-audit --strict --json
```

The strict audit currently exits `1` by design because the 50/100 summaries are
missing. A useful review result is `valid=true`, `claim_ready=false`, and
remaining requirements limited to:

| Requirement | Expected State |
| --- | --- |
| `produce_claim_valid_50_scene_summary` | Not satisfied until the 50-scene full-stage summary is present and clean. |
| `produce_claim_valid_100_scene_summary` | Not satisfied until the 100-scene full-stage summary is present and clean. |
| `pass_strict_claim_gate` | Not satisfied until all planned summaries are claim-valid. |

The audit's `objective_completion` object also exposes the current
`blocking_requirements`, `next_command_groups`, and `next_command_renderer_groups`
summary so reviewers can map the remaining claim gaps back to the command
renderer without executing private cache or rollout work. Its `scale_claim_gaps`
rows summarize each 50/100 stage's local/source cache validity, missing summary
state, blockers, and next command groups.
The tracked resume-command artifact adds `resume_plan`, a compact list of the
affected 50/100 stages, missing shard summary paths, per-shard scene windows,
validate-only cache preflight commands, and merge/promote/post repair steps
selected by the current audit, plus the completion-gate counts each promoted
summary must satisfy.

## Cleanup Boundary

If disk pressure returns after local probes or failed scale attempts, start with
`wod2sim-benchmark-cleanup --json`. It is dry-run by default, refuses to remove
paths with tracked files, and does not remove source `all-usdzs` assets or
generated 50/100 local USDZ caches unless `--include-gated-assets` or
`--include-scale-caches` is passed with `--apply`.

## Promotion Boundary

Shard summaries and diagnostic probes are operational evidence, not full-stage
claims. A 50/100 public claim requires a compact merged summary with the planned
shard inputs, the expected scene count, zero failed scenes, zero sensor-pipeline
failures, and successful promotion through `wod2sim-promote-batch-summary`.
`objective_completion.scale_claim_gaps[].merge_input_progress` reports how many
planned shard summary inputs are locally present and claim-valid when the audit
is run.

After promotion, refresh the public chain in this order:

```bash
wod2sim-benchmark-readiness --stable-public-snapshot --skip-runtime-probes --json
wod2sim-benchmark-status --json
wod2sim-benchmark-audit --strict --json
wod2sim-benchmark-evidence-manifest --json
```

Do not commit raw USDZ assets, Docker layers, Hugging Face caches, rollout videos, support bundles, or gated scene-derived files.
