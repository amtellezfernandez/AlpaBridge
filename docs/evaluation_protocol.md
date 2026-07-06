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
- WOD2Sim does not redistribute Waymo data, AlpaSim assets, private checkpoints,
  rollout videos, or support bundles.
- One recorded scene is integration evidence, not a broad benchmark result.

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

The strongest result is a paired example where the same policy appears acceptable
under open-loop evaluation but fails differently under closed-loop execution.

## Metrics

Closed-loop reports should include:

| Metric group | Examples |
| --- | --- |
| Driving outcome | collision rate, off-road rate, route progress, scenario completion, timeout rate |
| Runtime validity | valid-frame ratio, sensor freshness, action latency, late-message rate |
| Evidence validity | manifest present, audit valid, support bundle valid, support bundle hash present |
| Failure taxonomy | route drift, stale observations, heading-error compounding, recovery failure, lifecycle crash |

`wod2sim-batch-summary` is the compact artifact for multi-scene AlpaSim batches.
It reports per-scene completion, audited frames, closed-loop metric rates,
failure taxonomy, and local artifact hashes without embedding rollout videos or
scene assets.

## Scene Coverage

A workshop-scale evaluation should cover at least a small multi-scene set across
straight driving, turns, dense traffic, route merges, occlusion, and stop/go
cases. A stronger benchmark claim should scale to dozens of scenes and report
success/failure counts per route type.

Recommended progression:

| Stage | Preset | Claim strength |
| --- | --- | --- |
| Pilot | `front_camera_10scene_smoke` | Runtime stability and concrete closed-loop evidence. |
| Workshop-scale | `front_camera_50scene_public2602` | Multi-scene failure taxonomy and baseline comparison. |
| Stronger benchmark | `front_camera_100scene_public2602` | More credible aggregate rates and scenario diversity. |

The 50/100-scene stages require a metadata-valid local AlpaSim USDZ directory.
Build it from the Hugging Face artifact revision before running:

```bash
HF_TOKEN=... wod2sim-build-local-cache \
  --scene-preset front_camera_50scene_public2602 \
  --alpasim-root /path/to/alpasim \
  --local-usdz-dir /path/to/alpasim/data/nre-artifacts/local-2602-usdzs-50
```

Then pass the directory to AlpaSim:

```bash
wod2sim-batch ... \
  --scene-preset front_camera_50scene_public2602 \
  --wizard-arg scenes.local_usdz_dir=/path/to/alpasim/data/nre-artifacts/local-2602-usdzs-50
```

Execution roles:

| Role | Minimum Capability |
| --- | --- |
| Reviewer | Run tests, dry reproduction plans, summaries, and audits without private assets. |
| Cache builder | Download and validate public 26.02 USDZs with Hugging Face access and sufficient disk; GPU is not required. |
| Closed-loop runner | Execute live AlpaSim batches on x86_64 Linux with Docker, NVIDIA GPU runtime, AlpaSim images, and cached scene artifacts. |
| ARM/Linux host | Use for cache building or diagnostics; live sensorsim rollouts are blocked by default because the AlpaSim sensorsim image is amd64-only. |

Set `WAYSPAN_ALLOW_UNSUPPORTED_ALPASIM_ARM=1` only for an intentional unsupported
ARM rollout diagnostic.

Public releases should publish compact JSON summaries, metric tables, hashes,
and redistribution-cleared images only. Do not publish raw USDZ assets, rollout
videos, or support bundles containing gated content.

Current tracked pilot evidence:

| Artifact | Result |
| --- | --- |
| [`docs/evidence/closed_loop_spotlight_reflex_10scene_batch.json`](evidence/closed_loop_spotlight_reflex_10scene_batch.json) | 10/10 completed scenes, 1,990 audited frames, 0 failed scenes, 0 sensor-pipeline failures. |
| Failure taxonomy | 5 collision scenes, 2 at-fault collision scenes, 3 wrong-lane scenes, 0 offroad scenes, 7 low-progress scenes. |
| Claim boundary | Closed-loop integration evidence for `spotlight_reflex`, not a policy-quality benchmark claim. |

Current scale status:

| Stage | Public Artifact Status |
| --- | --- |
| 10-scene pilot | Tracked as the compact public JSON above. Raw AlpaSim media, support bundles, and gated scene artifacts are intentionally untracked. |
| 50-scene public 26.02 preset | Preset and cache-builder workflow are tracked. A claim-valid 50-scene closed-loop summary still requires rebuilding the local USDZ cache and executing on an x86_64 AlpaSim runner. |
| 100-scene public 26.02 preset | Preset and cache-builder workflow are tracked. A claim-valid 100-scene closed-loop summary still requires the same cache/runtime prerequisites at larger scale. |

The current machine-readable regeneration status is tracked at
[`docs/evidence/benchmark_regeneration_status_20260706.json`](evidence/benchmark_regeneration_status_20260706.json).
The matching command-level rerun plan is tracked at
[`docs/evidence/benchmark_regeneration_plan_20260706.json`](evidence/benchmark_regeneration_plan_20260706.json).
Its scale stages include 10-scene shard commands for constrained hosts; shard
summaries are operational checkpoints, not replacements for a complete 50/100
public summary. Validate the local USDZ cache offline with
`wod2sim-build-local-cache --validate-only` before launching shards. After all shards complete, merge their
compact summaries with `wod2sim-batch-summary --merge-summary ...
--expected-scene-count N`, then promote the validated summary with
`wod2sim-promote-batch-summary`.
Validation failures are machine-readable: `missing_scene_ids`,
`invalid_revision_scene_ids`, or `invalid_cache_files` must be resolved before
claim-valid scale shards are started.
The public claim gate for those artifacts is tracked at
[`docs/evidence/benchmark_regeneration_audit_20260706.json`](evidence/benchmark_regeneration_audit_20260706.json).
For merged scale summaries, the audit also verifies that the recorded shard
summary inputs match the regeneration plan.
