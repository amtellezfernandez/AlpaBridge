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

The 50/100-scene stages require a complete local AlpaSim scene cache or token
access to the public scene artifacts. Public releases should publish compact
JSON summaries, metric tables, hashes, and redistribution-cleared images only.

Current tracked pilot evidence:

| Artifact | Result |
| --- | --- |
| [`docs/evidence/closed_loop_spotlight_reflex_10scene_batch.json`](evidence/closed_loop_spotlight_reflex_10scene_batch.json) | 10/10 completed scenes, 1,990 audited frames, 0 failed scenes, 0 sensor-pipeline failures. |
| Failure taxonomy | 5 collision scenes, 2 at-fault collision scenes, 3 wrong-lane scenes, 0 offroad scenes, 7 low-progress scenes. |
| Claim boundary | Closed-loop integration evidence for `spotlight_reflex`, not a policy-quality benchmark claim. |
